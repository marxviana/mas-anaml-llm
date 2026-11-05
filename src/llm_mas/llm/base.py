"""LLM-Interface (ANA-ML 2.0): contrato entre agentes e serviços de LLM."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol


class LLMError(RuntimeError):
    pass


class BudgetExceeded(LLMError):
    """Erro que interrompe a execução inteira (limite de custo ou créditos esgotados)."""


class NoAnswer(LLMError):
    """O cliente não respondeu (ex.: ``DryRunLLM``); o componente usa sua política offline."""


def tolerate(exc: LLMError) -> None:
    """Componentes toleram falhas pontuais do LLM (recorrendo à política
    offline e contando a falha), mas nunca o fim do orçamento."""
    if isinstance(exc, BudgetExceeded):
        raise exc


class LLMRefusal(LLMError):
    def __init__(self, category: str | None, explanation: str | None = None) -> None:
        super().__init__(f"o modelo recusou a solicitação (categoria={category}): {explanation or ''}")
        self.category = category
        self.explanation = explanation


class LLMClient(Protocol):
    def generate(self, system: str, prompt: str) -> str:
        """Resposta em texto livre."""
        ...

    def generate_json(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Resposta estruturada, válida segundo o JSON Schema ``schema``."""
        ...


class FunctionLLM:
    """Adapta uma função Python ao contrato ``LLMClient``.

    Útil em testes e para reproduzir comportamentos observados em experimentos
    (ex.: o agente que envia mensagens a si mesmo, Fig. 7 de arXiv:2307.06187).
    A função recebe ``(system, prompt, schema)`` — ``schema`` é ``None`` em
    ``generate`` — e retorna texto ou um ``dict``.
    """

    def __init__(self, fn: Callable[[str, str, dict[str, Any] | None], str | dict[str, Any]]) -> None:
        self.fn = fn
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        out = self.fn(system, prompt, None)
        return out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)

    def generate_json(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((system, prompt))
        out = self.fn(system, prompt, schema)
        return out if isinstance(out, dict) else json.loads(out)
