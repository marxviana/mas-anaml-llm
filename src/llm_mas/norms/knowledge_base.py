"""Norm Knowledge Base (ANA-ML 2.0): repositório versionado de normas
predefinidas e geradas dinamicamente, com histórico auditável de mudanças."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from llm_mas.norms.norm import Deontic, Norm

if TYPE_CHECKING:
    from llm_mas.core.agent import Agent


@dataclass(frozen=True)
class NormChange:
    iteration: int
    norm_id: str
    before: Norm | None
    after: Norm | None
    rationale: str
    approved_by: str
    status: str = "applied"  # applied | rejected_validation | rejected_supervisor


class NormKnowledgeBase:
    def __init__(self, norms: Iterable[Norm] = ()) -> None:
        self._norms: dict[str, Norm] = {}
        self.history: list[NormChange] = []
        for n in norms:
            self.add(n)

    def add(self, norm: Norm) -> None:
        if norm.id in self._norms:
            raise ValueError(f"norma duplicada: {norm.id}")
        self._norms[norm.id] = norm

    def get(self, norm_id: str) -> Norm | None:
        return self._norms.get(norm_id)

    def __iter__(self):
        return iter(self._norms.values())

    def __len__(self) -> int:
        return len(self._norms)

    def put(self, norm: Norm, iteration: int, rationale: str, approved_by: str) -> NormChange:
        """Cria ou substitui uma norma, registrando a mudança."""
        change = NormChange(iteration, norm.id, self._norms.get(norm.id), norm, rationale, approved_by)
        self._norms[norm.id] = norm
        self.history.append(change)
        return change

    def record_rejection(self, iteration: int, norm_id: str, proposed: Norm | None, rationale: str, status: str) -> None:
        self.history.append(NormChange(iteration, norm_id, self._norms.get(norm_id), proposed, rationale, "-", status))

    # --- consultas -----------------------------------------------------------
    def of_kind(self, deontic: Deontic) -> list[Norm]:
        return [n for n in self._norms.values() if n.deontic == deontic]

    def applicable(self, ctx: dict[str, Any], deontic: Deontic) -> list[Norm]:
        """Normas cujo escopo casa com ``ctx``, já removidas as normas gerais
        substituídas por normas específicas aplicáveis."""
        candidates = [
            n for n in self.of_kind(deontic) if n.scope is None or n.scope.evaluate(ctx, n.parameters)
        ]
        overridden = {n.overrides for n in candidates if n.overrides}
        return [n for n in candidates if n.id not in overridden]

    def for_addressee(self, agent: Agent) -> list[Norm]:
        return [n for n in self._norms.values() if n.addressee in ("*", agent.id, agent.role)]

    def snapshot(self) -> list[dict[str, Any]]:
        return [n.to_dict() for n in self._norms.values()]
