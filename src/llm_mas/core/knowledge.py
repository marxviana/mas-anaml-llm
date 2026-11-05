"""Componente *Knowledge* do MAPE-K: objetivos, crenças e memória local.

O artigo arXiv:2307.06187 relata que, sem histórico, os agentes LLM não
mantinham personas consistentes entre iterações e aponta como trabalho futuro
"uma estrutura de memória local sintetizada como prompt". Esta classe é essa
memória: o agente registra o que percebeu e fez, e ``render`` a resume no prompt.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MemoryEntry:
    iteration: int
    kind: str
    content: str


class Knowledge:
    def __init__(
        self,
        goals: list[str] | None = None,
        beliefs: dict[str, Any] | None = None,
        memory_limit: int = 200,
    ) -> None:
        self.goals: list[str] = list(goals or [])
        self.beliefs: dict[str, Any] = dict(beliefs or {})
        self._memory: deque[MemoryEntry] = deque(maxlen=memory_limit)

    def remember(self, iteration: int, kind: str, content: str) -> None:
        self._memory.append(MemoryEntry(iteration, kind, content))

    def recent(self, n: int | None = None, kind: str | None = None) -> list[MemoryEntry]:
        entries = [e for e in self._memory if kind is None or e.kind == kind]
        return entries if n is None else entries[-n:]

    def render(self, n: int = 20) -> str:
        entries = self.recent(n)
        if not entries:
            return "(sem histórico)"
        return "\n".join(f"[it {e.iteration}] {e.kind}: {e.content}" for e in entries)
