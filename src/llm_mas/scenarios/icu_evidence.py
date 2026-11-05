"""Evidências imperfeitas para a decisão sobre alarmes na UTI.

O simulador conhece o estado oculto de cada paciente (em piora ou não, em que
estágio, se a leitura de SpO2 foi um artefato). Os agentes recebem apenas
observações ruidosas desse estado:

* achados clínicos à beira-leito, com sensibilidade e especificidade parciais
  (e achados basais em doenças crônicas, como dispneia na DPOC);
* indício de má qualidade do sinal, que nem sempre aparece quando há artefato
  e às vezes aparece sem artefato;
* a tendência das leituras recentes (montada em ``ICUEnv.decision_context``).

Também ficam aqui as duas referências de decisão:

* ``news_score`` — escore NEWS2 modificado, independente do gerador (é a
  política offline do agente de decisão);
* ``bayes_posterior`` — classificador ótimo que conhece o modelo gerador; serve
  só de teto para avaliar as políticas, nunca de política dos agentes.
"""

from __future__ import annotations

import math
import random
from typing import Any

# achado: (probabilidade quando estável, probabilidade no 1º estágio de piora,
#          incremento por estágio, teto)
FINDINGS: dict[str, tuple[float, float, float, float]] = {
    "dispneia": (0.10, 0.35, 0.08, 0.90),
    "sudorese": (0.08, 0.25, 0.08, 0.80),
    "consciencia_alterada": (0.04, 0.15, 0.07, 0.70),
    "perfusao_lenta": (0.10, 0.30, 0.08, 0.85),
    "queixa": (0.15, 0.40, 0.05, 0.80),
}
# achados basais de doenças crônicas (probabilidade quando estável)
CHRONIC_BASELINE = {("copd", "dispneia"): 0.50, ("low_bp", "perfusao_lenta"): 0.30}
ARTIFACT_SIGN = (0.10, 0.70)  # P(indício de artefato | sem artefato), P(... | com artefato)

PROFILE_TEXT = {
    "stable": "sem doença crônica relevante",
    "copd": "DPOC (doença pulmonar obstrutiva crônica)",
    "tachycardic": "taquicardia sinusal crônica",
    "low_bp": "hipotensão crônica",
}
FINDING_TEXT = {
    "dispneia": ("dispneia presente", "sem dispneia"),
    "sudorese": ("sudorese", "sem sudorese"),
    "consciencia_alterada": ("sonolento/confuso", "consciente e orientado"),
    "perfusao_lenta": ("enchimento capilar lento (> 3 s)", "enchimento capilar normal"),
    "queixa": ("refere mal-estar", "sem queixas"),
    "sinal_artefato": ("curva pletismográfica irregular, paciente se mexendo",
                       "curva pletismográfica de boa qualidade"),
}


def finding_probability(name: str, profile: str, stage: int) -> float:
    stable, start, inc, cap = FINDINGS[name]
    base = CHRONIC_BASELINE.get((profile, name), stable)
    if stage <= 0:
        return base
    return max(base, min(cap, start + inc * (stage - 1)))


def draw_findings(rng: random.Random, profile: str, stage: int, artifact: bool) -> dict[str, bool]:
    findings = {name: rng.random() < finding_probability(name, profile, stage) for name in FINDINGS}
    findings["sinal_artefato"] = rng.random() < ARTIFACT_SIGN[artifact]
    return findings


def bedside_text(findings: dict[str, bool]) -> str:
    return "; ".join(FINDING_TEXT[k][0 if v else 1] for k, v in findings.items()) + "."


# --------------------------------------------------------------------------
# Política offline: escore NEWS2 modificado
# --------------------------------------------------------------------------
NEWS_THRESHOLD = 5  # NEWS2: agregado ≥ 5 pede avaliação clínica urgente


def news_score(vitals: dict[str, float], profile: str, findings: dict[str, bool]) -> int:
    """NEWS2 (Royal College of Physicians, 2017) sobre a leitura que disparou o
    alarme — com a escala 2 de SpO2 para DPOC — acrescido de 1 ponto por achado
    clínico e −2 quando há indício de artefato. Não usa o modelo gerador."""
    s = 0
    spo2, rr, hr, sbp = vitals["spo2"], vitals["rr"], vitals["hr"], vitals["sbp"]
    if profile == "copd":  # escala 2: alvo de 88–92%
        s += 3 if spo2 <= 83 else 2 if spo2 <= 85 else 1 if spo2 <= 87 else 0
    else:
        s += 3 if spo2 <= 91 else 2 if spo2 <= 93 else 1 if spo2 <= 95 else 0
    s += 3 if rr <= 8 else 1 if rr <= 11 else 0 if rr <= 20 else 2 if rr <= 24 else 3
    s += 3 if hr <= 40 else 1 if hr <= 50 else 0 if hr <= 90 else 1 if hr <= 110 else 2 if hr <= 130 else 3
    s += 3 if sbp <= 90 else 2 if sbp <= 100 else 1 if sbp <= 110 else 0
    s += 3 if findings["consciencia_alterada"] else 0
    s += sum(findings[k] for k in ("dispneia", "sudorese", "perfusao_lenta", "queixa"))
    s -= 2 if findings["sinal_artefato"] else 0
    return s


# --------------------------------------------------------------------------
# Referência: classificador bayesiano com o modelo gerador
# --------------------------------------------------------------------------
def _log_normal(x: float, mean: float, sd: float) -> float:
    return -0.5 * ((x - mean) / sd) ** 2 - math.log(sd * math.sqrt(2 * math.pi))


def _loglik(vitals: dict[str, float], findings: dict[str, bool], profile: str, stage: int, artifact: bool,
            profiles: dict, deterioration: dict) -> float:
    ll = 0.0
    for v, x in vitals.items():
        mean, sd = profiles[profile][v]
        if v == "spo2" and artifact:
            ll += math.log(1 / 3.5) if 85.5 <= x <= 89.0 else -50.0
        else:
            ll += _log_normal(x, mean + deterioration[v] * stage, sd)
    for name in FINDINGS:
        p = finding_probability(name, profile, stage)
        ll += math.log(p if findings[name] else 1 - p)
    p = ARTIFACT_SIGN[artifact]
    return ll + math.log(p if findings["sinal_artefato"] else 1 - p)


def _logsumexp(xs: list[float]) -> float:
    m = max(xs)
    return m + math.log(sum(math.exp(x - m) for x in xs))


def bayes_posterior(vitals: dict[str, float], findings: dict[str, bool], profile: str, prior: float,
                    duration: int, artifact_rate: float, profiles: dict, deterioration: dict) -> float:
    """P(piora | leitura, achados), marginalizando o estágio (uniforme em
    1..duration) e a ocorrência de artefato."""
    def lik(stages: list[int]) -> float:
        terms = [_loglik(vitals, findings, profile, s, a, profiles, deterioration)
                 + math.log(artifact_rate if a else 1 - artifact_rate) - math.log(len(stages))
                 for s in stages for a in (False, True)]
        return _logsumexp(terms)

    prior = min(max(prior, 1e-6), 1 - 1e-6)
    log_det = math.log(prior) + lik(list(range(1, duration + 1)))
    log_stable = math.log(1 - prior) + lik([0])
    return 1 / (1 + math.exp(log_stable - log_det))


def classification_stats(pairs: list[tuple[bool, bool]]) -> dict[str, Any]:
    """``pairs`` = [(previsto, verdadeiro)] → acurácia, sensibilidade, especificidade."""
    if not pairs:
        return {"n": 0, "accuracy": None, "sensitivity": None, "specificity": None}
    pos = [p for p, t in pairs if t]
    neg = [p for p, t in pairs if not t]
    return {
        "n": len(pairs),
        "accuracy": round(sum(p == t for p, t in pairs) / len(pairs), 3),
        "sensitivity": round(sum(pos) / len(pos), 3) if pos else None,
        "specificity": round(sum(not p for p in neg) / len(neg), 3) if neg else None,
    }
