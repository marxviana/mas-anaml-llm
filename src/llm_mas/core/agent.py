"""Agentes autoadaptativos com o laço MAPE-K.

``Agent`` implementa o laço clássico (Monitor → Analyze/Plan → Execute, com
Knowledge). ``LLMAgent`` segue a arquitetura LLM-based MAPE-K do artigo
arXiv:2307.06187 (Fig. 3): o *Monitor* consolida sensores e mensagens recebidas
em um prompt; o LLM encapsula Analyze, Plan e Knowledge; o *Execute* traduz a
saída do LLM em ações.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from llm_mas.core.knowledge import Knowledge
from llm_mas.core.messages import Action, Message
from llm_mas.llm.base import LLMError, tolerate
from llm_mas.llm.parsing import ACTION_FORMAT_HELP, parse_actions

if TYPE_CHECKING:
    from llm_mas.core.environment import Environment
    from llm_mas.llm.base import LLMClient
    from llm_mas.norms.monitor import NormEvent


@dataclass
class Perception:
    iteration: int
    messages: list[Message] = field(default_factory=list)
    sensors: dict[str, Any] = field(default_factory=dict)


class Agent(ABC):
    def __init__(self, agent_id: str, role: str, knowledge: Knowledge | None = None) -> None:
        self.id = agent_id
        self.role = role
        self.knowledge = knowledge or Knowledge()
        self.env: Environment | None = None
        self.score = 0.0
        self._rng: random.Random | None = None

    def bind(self, env: Environment) -> None:
        self.env = env
        self._rng = None

    @property
    def rng(self) -> random.Random:
        """Gerador aleatório próprio: os sorteios de um agente não dependem de
        quantos sorteios os outros fizeram antes dele."""
        if self._rng is None:
            assert self.env is not None
            self._rng = self.env.agent_rng(self.id)
        return self._rng

    # --- laço MAPE-K -------------------------------------------------------
    def step(self, iteration: int) -> list[Action]:
        perception = self.monitor(iteration)
        plan = self.analyze_and_plan(perception)
        return self.execute(plan, iteration)

    def monitor(self, iteration: int) -> Perception:
        assert self.env is not None, f"agente {self.id} não está registrado em um ambiente"
        messages = self.env.collect(self.id)
        for m in messages:
            self.knowledge.remember(iteration, "recebida", f"{m.sender} → {m.content}")
        return Perception(iteration, messages, self.sense(iteration))

    def sense(self, iteration: int) -> dict[str, Any]:
        """Sensores do elemento gerenciado. Subclasses leem o ambiente aqui."""
        return {}

    @abstractmethod
    def analyze_and_plan(self, perception: Perception) -> list[Action]: ...

    def execute(self, plan: list[Action], iteration: int) -> list[Action]:
        for action in plan:
            action.iteration = iteration
            if action.type == "send":
                self.knowledge.remember(
                    iteration, "enviada", f"{action.data['receiver']} ← {action.data['content']}"
                )
            else:
                self.knowledge.remember(iteration, "ação", f"{action.type} {action.data}")
        return plan

    # --- retroalimentação normativa ----------------------------------------
    def on_norm_event(self, event: NormEvent) -> None:
        """Sanções e recompensas chegam ao agente e entram em sua memória,
        permitindo que ele adapte o comportamento nas iterações seguintes."""
        self.score += event.delta
        self.knowledge.remember(event.iteration, "norma", event.describe())


class LLMAgent(Agent):
    """Agente cujo raciocínio é delegado a um LLM.

    Com ``llm=None`` o agente usa ``heuristic`` — uma política determinística
    que produz texto no mesmo formato de ação — para rodar sem API e em testes.
    """

    def __init__(
        self,
        agent_id: str,
        role: str,
        llm: LLMClient | None = None,
        knowledge: Knowledge | None = None,
        memory_window: int = 20,
    ) -> None:
        super().__init__(agent_id, role, knowledge)
        self.llm = llm
        self.memory_window = memory_window
        self.last_output = ""

    def system_prompt(self) -> str:
        goals = "\n".join(f"- {g}" for g in self.knowledge.goals) or "- (não definidos)"
        return (
            f"Você é o agente {self.id} (papel: {self.role}) em um sistema multiagente.\n"
            f"Objetivos:\n{goals}\n\n{ACTION_FORMAT_HELP}"
        )

    def build_prompt(self, perception: Perception) -> str:
        assert self.env is not None
        parts = [f"Iteração atual: {perception.iteration} de {self.env.max_iterations or '?'}"]
        norms = self.env.norms_text_for(self)
        if norms:
            parts.append(f"Normas que se aplicam a você:\n{norms}")
        parts.append(f"Sua memória (mais recentes por último):\n{self.knowledge.render(self.memory_window)}")
        if perception.messages:
            msgs = "\n".join(f"- {m.sender}: {m.content}" for m in perception.messages)
            parts.append(f"Mensagens recebidas nesta iteração:\n{msgs}")
        else:
            parts.append("Nenhuma mensagem nova nesta iteração.")
        if perception.sensors:
            sensors = "\n".join(f"- {k}: {v}" for k, v in perception.sensors.items())
            parts.append(f"Sensores:\n{sensors}")
        notices = self.env.pop_notices(self.id)
        if notices:
            parts.append("Avisos do ambiente sobre a iteração anterior:\n" + "\n".join(f"- {n}" for n in notices))
        parts.append("Decida suas ações para esta iteração.")
        return "\n\n".join(parts)

    def should_deliberate(self, perception: Perception) -> bool:
        """``False`` quando o agente não tem mais o que decidir (ex.: já vendeu
        o livro) — evita uma chamada paga ao LLM sem efeito possível."""
        return True

    def analyze_and_plan(self, perception: Perception) -> list[Action]:
        if not self.should_deliberate(perception):
            return []
        if self.llm is None:
            text = self.heuristic(perception)
        else:
            try:
                text = self.llm.generate(self.system_prompt(), self.build_prompt(perception))
            except LLMError as exc:  # falha pontual: usa a política offline e registra
                tolerate(exc)
                assert self.env is not None
                self.env.state["llm_failures"] = self.env.state.get("llm_failures", 0) + 1
                text = self.heuristic(perception)
        self.last_output = text
        return self.interpret(perception, text)

    def interpret(self, perception: Perception, text: str) -> list[Action]:
        return parse_actions(text, self.id)

    def heuristic(self, perception: Perception) -> str:
        raise NotImplementedError(f"{type(self).__name__} não define política offline; forneça um LLM.")
