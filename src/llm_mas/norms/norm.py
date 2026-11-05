"""Normas deônticas (conceitos do metamodelo ANA / ANA-ML).

* ``scope``      — a que instâncias (fatos/ações) a norma se aplica;
* ``activation`` — quando a norma está ativa (para obrigações, avaliada sobre
                   os fatos do ambiente; para proibições, sobre a ação);
* ``target``     — a ação regulada (obrigatória ou proibida);
* ``parameters`` — valores referenciados por ``$nome`` nas condições; são o que
                   o motor de adaptação refina;
* ``overrides``  — uma norma específica (ex.: por paciente) que substitui a
                   norma geral quando seu ``scope`` casa com o fato.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from llm_mas.norms.condition import Condition


class Deontic(str, Enum):
    OBLIGATION = "obligation"
    PROHIBITION = "prohibition"
    PERMISSION = "permission"


@dataclass(frozen=True)
class Norm:
    id: str
    description: str
    deontic: Deontic
    addressee: str  # id de agente, papel ou "*"
    target: Condition
    activation: Condition | None = None
    scope: Condition | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    deadline: int = 1  # obrigações: iterações para cumprir após a ativação
    persistence: int = 1  # iterações consecutivas de ativação antes de valer
    sanction: float = 0.0
    reward: float = 0.0
    adaptable: bool = True
    overrides: str | None = None
    rearm: bool = False  # obrigações: reabrir enquanto a ativação persistir após cumprir/expirar
    regimented: bool = False  # inviolável: a arquitetura impede o agente de descumpri-la
    version: int = 1

    def with_changes(self, **changes: Any) -> Norm:
        return replace(self, version=self.version + 1, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "deontic": self.deontic.value,
            "addressee": self.addressee,
            "target": self.target.to_dict(),
            "activation": self.activation.to_dict() if self.activation else None,
            "scope": self.scope.to_dict() if self.scope else None,
            "parameters": dict(self.parameters),
            "deadline": self.deadline,
            "persistence": self.persistence,
            "sanction": self.sanction,
            "reward": self.reward,
            "adaptable": self.adaptable,
            "overrides": self.overrides,
            "rearm": self.rearm,
            "regimented": self.regimented,
            "version": self.version,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Norm:
        def cond(key: str) -> Condition | None:
            return Condition.from_dict(data[key]) if data.get(key) else None

        return Norm(
            id=data["id"],
            description=data["description"],
            deontic=Deontic(data["deontic"]),
            addressee=data["addressee"],
            target=Condition.from_dict(data["target"]),
            activation=cond("activation"),
            scope=cond("scope"),
            parameters=dict(data.get("parameters", {})),
            deadline=int(data.get("deadline", 1)),
            persistence=int(data.get("persistence", 1)),
            sanction=float(data.get("sanction", 0.0)),
            reward=float(data.get("reward", 0.0)),
            adaptable=bool(data.get("adaptable", True)),
            overrides=data.get("overrides"),
            rearm=bool(data.get("rearm", False)),
            regimented=bool(data.get("regimented", False)),
            version=int(data.get("version", 1)),
        )
