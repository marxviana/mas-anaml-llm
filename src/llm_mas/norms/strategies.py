"""Estratégias de deliberação normativa (fase 2): cumprir ou violar uma norma.

Implementa a etapa NormDeliberation → NormCompliance do processo normativo do
metamodelo ANA (Viana et al., IEEE Access 2022), com estratégias inspiradas em
López y López, Luck e d'Inverno (AAMAS 2002) e no framework JSAN. As definições
originais são qualitativas; aqui cada uma é operacionalizada sobre a mesma
informação que o agente LLM recebe:

* ``social``        — sempre cumpre;
* ``rebellious``    — viola sempre que a arquitetura permite;
* ``selfish``       — viola quando a violação favorece os próprios objetivos,
                      ignorando sanções;
* ``pressured``     — cumpre quando a punição esperada (detecção × sanção)
                      mais a recompensa de cumprir supera o ganho de violar;
* ``opportunistic`` — viola quando favorece seus objetivos e julga improvável
                      ser fiscalizado (detecção < 0,5).

Normas regimentadas (``Norm.regimented``) não chegam à deliberação: a
arquitetura obriga o cumprimento.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DeliberationCase:
    """O que o agente sabe ao deliberar sobre uma norma (ou grupo de normas)."""

    norm_ids: tuple[str, ...]
    reward: float  # recompensa por cumprir
    sanction: float  # sanção se a violação for detectada
    detection: float  # probabilidade de detecção conhecida pelo agente
    violation_gain: float  # efeito da violação nos objetivos do agente (negativo = prejudica)


@dataclass(frozen=True)
class NormDecision:
    comply: bool
    reason: str


class NormStrategy(Protocol):
    name: str

    def decide(self, case: DeliberationCase) -> NormDecision: ...


class Social:
    name = "social"

    def decide(self, case: DeliberationCase) -> NormDecision:
        return NormDecision(True, "cumpre toda norma")


class Rebellious:
    name = "rebellious"

    def decide(self, case: DeliberationCase) -> NormDecision:
        return NormDecision(False, "viola sempre que possível")


class Selfish:
    name = "selfish"

    def decide(self, case: DeliberationCase) -> NormDecision:
        if case.violation_gain > 0:
            return NormDecision(False, f"violar favorece seus objetivos (ganho {case.violation_gain:g})")
        return NormDecision(True, "violar não favorece seus objetivos")


class Pressured:
    name = "pressured"

    def decide(self, case: DeliberationCase) -> NormDecision:
        cost = case.detection * case.sanction + case.reward
        if case.violation_gain > cost:
            return NormDecision(False, f"ganho {case.violation_gain:g} > punição esperada + recompensa {cost:g}")
        return NormDecision(True, f"punição esperada + recompensa {cost:g} ≥ ganho {case.violation_gain:g}")


class Opportunistic:
    name = "opportunistic"
    threshold = 0.5

    def decide(self, case: DeliberationCase) -> NormDecision:
        if case.violation_gain > 0 and case.detection < self.threshold:
            return NormDecision(False, f"favorece seus objetivos e a fiscalização é improvável (p={case.detection:g})")
        return NormDecision(True, "não compensa arriscar a fiscalização" if case.violation_gain > 0
                            else "violar não favorece seus objetivos")


STRATEGIES: dict[str, type] = {s.name: s for s in (Social, Rebellious, Selfish, Pressured, Opportunistic)}


def make_strategy(name: str) -> NormStrategy:
    try:
        return STRATEGIES[name]()
    except KeyError:
        raise ValueError(f"estratégia desconhecida: {name!r} (opções: {', '.join(STRATEGIES)})") from None
