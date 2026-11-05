"""Monitoramento e execução de normas (enforcement).

* Proibições são avaliadas sobre cada ação aplicada na iteração.
* Obrigações são abertas a partir dos fatos do ambiente: quando a ativação de
  uma norma vale por ``persistence`` iterações consecutivas para um fato, abre-se
  uma obrigação para o destinatário, que deve executar uma ação que satisfaça
  ``target`` com ``subject == fato["id"]`` em até ``deadline`` iterações.
  A obrigação fica "travada" até a ativação deixar de valer, para não reabrir
  a cada iteração do mesmo episódio — exceto em normas com ``rearm``, que
  reabrem enquanto a condição persistir (ex.: tarefa continua sem responsável).
  A trava e a contagem de persistência são da norma geral: quando uma norma
  específica passa a substituí-la, o episódio em curso não gera novo alarme.

Sanções e recompensas são entregues aos agentes (``Agent.on_norm_event``),
fechando o ciclo de adaptação do comportamento.

Fiscalização imperfeita (fase 2): cada violação é detectada com probabilidade
``detection`` (por norma ou padrão). Uma violação não detectada fica registrada
(``NormEvent.detected = False``) para o pesquisador, mas não gera sanção nem
chega ao agente — é o que torna possível o comportamento oportunista.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from llm_mas.core.messages import Action
from llm_mas.norms.knowledge_base import NormKnowledgeBase
from llm_mas.norms.norm import Deontic, Norm

if TYPE_CHECKING:
    from llm_mas.core.agent import Agent


@dataclass(frozen=True)
class NormEvent:
    kind: str  # violation | fulfillment
    norm_id: str
    agent: str
    iteration: int
    delta: float
    detail: str = ""
    subject: str | None = None
    detected: bool = True

    def describe(self) -> str:
        verb = "VIOLOU" if self.kind == "violation" else "cumpriu"
        sign = f"{self.delta:+g}"
        return f"{verb} a norma {self.norm_id} ({sign} pontos). {self.detail}".strip()


@dataclass
class Obligation:
    norm: Norm
    subject: str
    opened: int
    due: int
    fact: dict[str, Any] = field(default_factory=dict)
    fulfilled_at: int | None = None


def addressed_to(norm: Norm, agent: Agent) -> bool:
    return norm.addressee in ("*", agent.id, agent.role)


class NormMonitor:
    def __init__(self, kb: NormKnowledgeBase, detection: float | dict[str, float] = 1.0,
                 seed: int | str | None = None) -> None:
        self.kb = kb
        self.detection = detection
        self._seed = seed
        self.events: list[NormEvent] = []
        self.open_obligations: list[Obligation] = []
        self.closed_obligations: list[Obligation] = []
        self._streak: dict[tuple[str, str], int] = defaultdict(int)
        self._latched: set[tuple[str, str]] = set()

    def pending_for(self, agent: Agent) -> list[Obligation]:
        return [o for o in self.open_obligations if addressed_to(o.norm, agent)]

    # --- verificação das ações da iteração ----------------------------------
    def check(self, iteration: int, actions: list[Action], agents: dict[str, Agent]) -> list[NormEvent]:
        new: list[NormEvent] = []
        for action in actions:
            agent = agents.get(action.agent)
            if agent is None:
                continue
            ctx = {**action.as_context(), "role": agent.role}
            for norm in self.kb.applicable(ctx, Deontic.PROHIBITION):
                if not addressed_to(norm, agent):
                    continue
                if norm.activation and not norm.activation.evaluate(ctx, norm.parameters):
                    continue
                if norm.target.evaluate(ctx, norm.parameters):
                    new.append(NormEvent("violation", norm.id, agent.id, iteration, -norm.sanction,
                                         norm.description, action.data.get("subject")))

        still_open: list[Obligation] = []
        for ob in self.open_obligations:
            fulfiller = self._fulfiller(ob, actions, agents)
            if fulfiller is not None:
                ob.fulfilled_at = iteration
                new.append(NormEvent("fulfillment", ob.norm.id, fulfiller.id, iteration, ob.norm.reward,
                                     f"obrigação sobre {ob.subject}", ob.subject))
            elif iteration >= ob.due:
                for agent in agents.values():
                    if addressed_to(ob.norm, agent):
                        new.append(NormEvent("violation", ob.norm.id, agent.id, iteration, -ob.norm.sanction,
                                             f"prazo expirado para {ob.subject}: {ob.norm.description}", ob.subject))
            else:
                still_open.append(ob)
                continue
            self.closed_obligations.append(ob)
            if ob.norm.rearm:
                self._latched.discard(self._key(ob.norm, ob.subject))
        self.open_obligations = still_open

        new = [self._enforce(e) for e in new]
        for event in new:
            if event.agent in agents and event.detected:
                agents[event.agent].on_norm_event(event)
        self.events.extend(new)
        return new

    def detection_probability(self, norm_id: str) -> float:
        if isinstance(self.detection, dict):
            base = norm_id.split("@")[0]
            return self.detection.get(norm_id, self.detection.get(base, self.detection.get("*", 1.0)))
        return self.detection

    def _enforce(self, event: NormEvent) -> NormEvent:
        if event.kind != "violation":
            return event
        p = self.detection_probability(event.norm_id)
        # sorteio próprio de cada violação: a mesma violação, em condições pareadas, tem o mesmo desfecho
        draw = random.Random(f"{self._seed}:enforcement:{event.norm_id}:{event.subject}:{event.agent}:{event.iteration}")
        if p >= 1.0 or draw.random() < p:
            return event
        return NormEvent(event.kind, event.norm_id, event.agent, event.iteration, 0.0,
                         event.detail + " (não detectada)", event.subject, detected=False)

    def _fulfiller(self, ob: Obligation, actions: list[Action], agents: dict[str, Agent]) -> Agent | None:
        for action in actions:
            agent = agents.get(action.agent)
            if agent is None or not addressed_to(ob.norm, agent) or action.data.get("subject") != ob.subject:
                continue
            # uma ação que declara as normas que cumpre (ex.: um alarme) só cumpre essas — um alarme
            # de outra norma para o mesmo paciente não cumpre uma obrigação que o agente decidiu violar
            if "norms" in action.data and ob.norm.id not in action.data["norms"]:
                continue
            ctx = {**action.as_context(), "role": agent.role}
            if ob.norm.target.evaluate(ctx, ob.norm.parameters):
                return agent
        return None

    @staticmethod
    def _key(norm: Norm, subject: str) -> tuple[str, str]:
        return (norm.overrides or norm.id, subject)

    # --- abertura de obrigações a partir dos fatos ---------------------------
    def open(self, iteration: int, facts: list[dict[str, Any]]) -> list[Obligation]:
        opened: list[Obligation] = []
        for fact in facts:
            for norm in self.kb.applicable(fact, Deontic.OBLIGATION):
                key = self._key(norm, str(fact["id"]))
                active = norm.activation is None or norm.activation.evaluate(fact, norm.parameters)
                if not active:
                    self._streak[key] = 0
                    self._latched.discard(key)
                    continue
                self._streak[key] += 1
                if self._streak[key] >= norm.persistence and key not in self._latched:
                    ob = Obligation(norm, str(fact["id"]), iteration, iteration + norm.deadline, dict(fact))
                    self.open_obligations.append(ob)
                    self._latched.add(key)
                    opened.append(ob)
        return opened

    # --- estatísticas -------------------------------------------------------
    def summary(self) -> dict[str, Any]:
        by_norm: dict[str, dict[str, int]] = defaultdict(lambda: {"violation": 0, "fulfillment": 0})
        for e in self.events:
            by_norm[e.norm_id][e.kind] += 1
        return {
            "violations": sum(v["violation"] for v in by_norm.values()),
            "fulfillments": sum(v["fulfillment"] for v in by_norm.values()),
            "by_norm": dict(by_norm),
        }
