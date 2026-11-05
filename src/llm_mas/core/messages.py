"""Mensagens trocadas entre agentes e ações produzidas pelos efetuadores."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Message:
    """Mensagem entregue pelo canal de comunicação do ambiente."""

    sender: str
    receiver: str
    content: str
    iteration: int
    performative: str = "inform"


@dataclass
class Action:
    """Ação emitida na etapa *Execute* do laço MAPE-K.

    ``type`` identifica o efetuador (``send``, ``alert``, ``assign``...). ``data``
    carrega os atributos da ação; o ambiente pode enriquecê-los ao aplicá-la
    (por exemplo, extraindo o comando de uma mensagem) para que o monitor de
    normas avalie a ação com o contexto completo.
    """

    agent: str
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    iteration: int = 0

    def as_context(self) -> dict[str, Any]:
        return {"agent": self.agent, "type": self.type, "iteration": self.iteration, **self.data}

    @staticmethod
    def send(agent: str, receiver: str, content: str, **data: Any) -> Action:
        return Action(agent, "send", {"receiver": receiver, "content": content, **data})
