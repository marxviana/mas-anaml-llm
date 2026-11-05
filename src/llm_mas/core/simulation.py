"""Executor da simulação em rodadas síncronas.

Ordem de cada iteração *t*:

1. ``env.update(t)``          — o elemento gerenciado evolui;
2. ``env.deliver()``          — mensagens da iteração anterior chegam;
3. todos os agentes executam o laço MAPE-K sobre o mesmo estado (em paralelo
   quando há agentes LLM) — nenhuma ação é aplicada nesta fase;
4. ``env.apply_round``        — as ações são aplicadas juntas, com disputas
                                resolvidas por regra explícita do cenário;
5. ``monitor.check``          — proibições e cumprimento/expiração de obrigações;
6. ``monitor.open``           — novas obrigações a partir dos fatos de *t*;
7. ``adaptation.maybe_adapt`` — o motor de adaptação pode refinar normas.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from llm_mas.core.agent import Agent
from llm_mas.core.environment import Environment
from llm_mas.core.messages import Action

if TYPE_CHECKING:
    from llm_mas.norms.adaptation import NormAdaptationEngine, NormChange
    from llm_mas.norms.monitor import NormEvent


@dataclass
class SimulationResult:
    iterations: int
    actions: list[Action]
    norm_events: list[NormEvent] = field(default_factory=list)
    norm_changes: list[NormChange] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def violations(self) -> list[NormEvent]:
        return [e for e in self.norm_events if e.kind == "violation"]


class Simulation:
    """``parallel=None`` decide sozinho: paraleliza quando algum agente usa LLM
    (as chamadas à API dominam o tempo); agentes heurísticos rodam em sequência."""

    def __init__(
        self,
        env: Environment,
        iterations: int,
        adaptation: NormAdaptationEngine | None = None,
        on_iteration: Callable[[int, list[Action]], None] | None = None,
        parallel: bool | None = None,
        max_workers: int = 8,
    ) -> None:
        self.env = env
        self.iterations = iterations
        self.adaptation = adaptation
        self.on_iteration = on_iteration
        self.parallel = parallel
        self.max_workers = max_workers
        env.max_iterations = iterations

    def _decide(self, agents: list[Agent], t: int) -> list[list[Action]]:
        parallel = self.parallel
        if parallel is None:
            parallel = any(getattr(a, "llm", None) is not None for a in agents)
        if not parallel or len(agents) < 2:
            return [a.step(t) for a in agents]
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(agents))) as pool:
            return list(pool.map(lambda a: a.step(t), agents))

    def run(self) -> SimulationResult:
        env = self.env
        for t in range(1, self.iterations + 1):
            env.iteration = t
            env.update(t)
            env.deliver()
            actions = [a for plan in self._decide(list(env.agents.values()), t) for a in plan]
            env.apply_round(actions)
            if env.monitor is not None:
                env.monitor.check(t, actions, env.agents)
                env.monitor.open(t, env.facts())
            if self.adaptation is not None and t < self.iterations:  # na última, não teria efeito
                self.adaptation.maybe_adapt(t, env)
            if self.on_iteration:
                self.on_iteration(t, actions)
            if getattr(env, "done", False):
                break
        return SimulationResult(
            iterations=env.iteration,
            actions=list(env.log),
            norm_events=list(env.monitor.events) if env.monitor else [],
            norm_changes=list(env.norms.history) if env.norms else [],
            scores={a.id: a.score for a in env.agents.values()},
            metrics=env.metrics(),
        )
