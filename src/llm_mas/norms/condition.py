"""Linguagem de condições das normas.

Condições são dados (não código) para que possam ser serializadas, mostradas
ao LLM, propostas por ele e validadas antes de entrar em vigor. Valores podem
referenciar:

* ``"$nome"`` — um parâmetro da norma (o que a adaptação altera);
* ``"@campo"`` — outro campo do mesmo contexto (ex.: ``receiver == @agent``).
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Any

_OPS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
    "in": lambda a, b: a in b,
    "contains": lambda a, b: b in a,
}


@dataclass(frozen=True)
class Comparison:
    var: str
    op: str
    value: Any

    def __post_init__(self) -> None:
        if self.op not in _OPS:
            raise ValueError(f"operador desconhecido: {self.op!r}")

    def evaluate(self, ctx: dict[str, Any], params: dict[str, Any]) -> bool:
        if self.var not in ctx:
            return False
        value = self.value
        if isinstance(value, str) and value.startswith("$"):
            if value[1:] not in params:
                return False
            value = params[value[1:]]
        elif isinstance(value, str) and value.startswith("@"):
            if value[1:] not in ctx:
                return False
            value = ctx[value[1:]]
        try:
            return bool(_OPS[self.op](ctx[self.var], value))
        except TypeError:
            return False

    def __str__(self) -> str:
        return f"{self.var} {self.op} {self.value}"


@dataclass(frozen=True)
class Condition:
    """Conjunção ``all_of`` e disjunção ``any_of``; ambas precisam valer
    (uma lista vazia é verdadeira)."""

    all_of: tuple[Comparison, ...] = ()
    any_of: tuple[Comparison, ...] = ()

    @staticmethod
    def all(*comparisons: tuple[str, str, Any]) -> Condition:
        return Condition(all_of=tuple(Comparison(*c) for c in comparisons))

    @staticmethod
    def any(*comparisons: tuple[str, str, Any]) -> Condition:
        return Condition(any_of=tuple(Comparison(*c) for c in comparisons))

    def evaluate(self, ctx: dict[str, Any], params: dict[str, Any] | None = None) -> bool:
        params = params or {}
        if not all(c.evaluate(ctx, params) for c in self.all_of):
            return False
        return not self.any_of or any(c.evaluate(ctx, params) for c in self.any_of)

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_of": [[c.var, c.op, c.value] for c in self.all_of],
            "any_of": [[c.var, c.op, c.value] for c in self.any_of],
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Condition:
        return Condition(
            all_of=tuple(Comparison(*c) for c in data.get("all_of", [])),
            any_of=tuple(Comparison(*c) for c in data.get("any_of", [])),
        )

    def __str__(self) -> str:
        parts = [" E ".join(map(str, self.all_of))] if self.all_of else []
        if self.any_of:
            parts.append("(" + " OU ".join(map(str, self.any_of)) + ")")
        return " E ".join(parts) or "sempre"
