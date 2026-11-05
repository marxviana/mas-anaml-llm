"""Ambiente compartilhado: registro de agentes, canal de mensagens e estado.

Mensagens enviadas na iteração *t* são entregues no início da iteração *t+1*,
como no cenário do artigo (uma mensagem por iteração, respondida na seguinte).

O resultado não depende da ordem em que os agentes foram registrados:

* as ações de uma rodada são aplicadas juntas (``apply_round``), depois que
  todos decidiram sobre o mesmo estado;
* mensagens da mesma rodada chegam em ordem canônica embaralhada pela semente,
  de modo que a posição na caixa de entrada não favorece nenhum remetente;
* cada agente tem seu próprio gerador aleatório (``agent_rng``).
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from llm_mas.core.messages import Action, Message

if TYPE_CHECKING:
    from llm_mas.core.agent import Agent
    from llm_mas.norms.knowledge_base import NormKnowledgeBase
    from llm_mas.norms.monitor import NormMonitor


class Environment:
    def __init__(self, name: str = "env", seed: int | None = None) -> None:
        self.name = name
        self.seed = seed
        self.rng = random.Random(seed)  # dinâmica do ambiente
        self._delivery_rng = random.Random(f"{seed}:delivery")
        self.agents: dict[str, Agent] = {}
        self.iteration = 0
        self.max_iterations: int | None = None
        self.state: dict[str, Any] = {}
        self.log: list[Action] = []
        self.norms: NormKnowledgeBase | None = None
        self.monitor: NormMonitor | None = None
        self._pending: list[Message] = []
        self._mailboxes: dict[str, list[Message]] = defaultdict(list)
        self._notices: dict[str, list[str]] = defaultdict(list)

    # --- avisos do ambiente ------------------------------------------------------
    def notify(self, agent_id: str, text: str) -> None:
        """Retorno do ambiente a um agente (ex.: um comando que não teve efeito)."""
        self._notices[agent_id].append(text)

    def pop_notices(self, agent_id: str) -> list[str]:
        return self._notices.pop(agent_id, [])

    def use_norms(self, kb: NormKnowledgeBase, detection: float | dict[str, float] = 1.0) -> NormMonitor:
        """Torna o ambiente normativo: os agentes passam a ver as normas e o
        monitor passa a verificá-las a cada iteração. ``detection`` é a
        probabilidade de uma violação ser detectada (1.0 = fiscalização perfeita)."""
        from llm_mas.norms.monitor import NormMonitor

        self.norms = kb
        self.monitor = NormMonitor(kb, detection, seed=self.seed)
        return self.monitor

    # --- agentes ------------------------------------------------------------
    def register(self, agent: Agent) -> Agent:
        if agent.id in self.agents:
            raise ValueError(f"agente duplicado: {agent.id}")
        self.agents[agent.id] = agent
        agent.bind(self)
        return agent

    def agents_with_role(self, role: str) -> list[Agent]:
        return [a for a in self.agents.values() if a.role == role]

    def agent_rng(self, agent_id: str) -> random.Random:
        return random.Random(f"{self.seed}:agent:{agent_id}")

    # --- canal de comunicação -------------------------------------------------
    def post(self, message: Message) -> None:
        self._pending.append(message)

    def deliver(self) -> None:
        # ordenar antes de embaralhar torna a permutação independente da ordem de envio
        self._pending.sort(key=lambda m: (m.sender, m.receiver, m.content, m.performative))
        self._delivery_rng.shuffle(self._pending)
        for m in self._pending:
            self._mailboxes[m.receiver].append(m)
        self._pending.clear()

    def collect(self, agent_id: str) -> list[Message]:
        return self._mailboxes.pop(agent_id, [])

    # --- dinâmica (pontos de extensão dos cenários) -------------------------
    def update(self, iteration: int) -> None:
        """Evolui o elemento gerenciado antes de os agentes agirem."""

    def apply_round(self, actions: list[Action]) -> None:
        """Aplica as ações de uma rodada. Cenários com disputas por recursos
        (ex.: dois vendedores confirmando ao mesmo comprador) sobrescrevem para
        resolvê-las com uma regra explícita."""
        for action in sorted(actions, key=lambda a: a.agent):  # ordenação estável
            self.apply(action)

    def apply(self, action: Action) -> None:
        """Aplica a ação ao ambiente. Cenários sobrescrevem para efeitos de
        domínio, mas devem chamar ``super().apply`` para o envio de mensagens."""
        self.log.append(action)
        if action.type == "send":
            receiver = action.data["receiver"]
            if receiver not in self.agents:
                action.data["delivered"] = False
                return
            action.data["delivered"] = True
            self.post(
                Message(
                    action.agent,
                    receiver,
                    action.data["content"],
                    action.iteration,
                    action.data.get("performative", "inform"),
                )
            )

    def facts(self) -> list[dict[str, Any]]:
        """Fatos observáveis sobre os quais normas de obrigação são ativadas.
        Cada fato deve ter um campo ``id`` (ex.: o paciente ou a tarefa)."""
        return []

    def metrics(self) -> dict[str, Any]:
        return {}

    def norms_text_for(self, agent: Agent) -> str:
        if self.norms is None:
            return ""
        return "\n".join(f"- [{n.id}] {n.description}" for n in self.norms.for_addressee(agent))
