"""Equivalência entre o caminho com LLM e as políticas offline.

Cada "LLM simulado" abaixo recebe SOMENTE o texto do prompt (e o esquema),
extrai dele a informação e aplica a mesma regra da política offline. Se a
simulação resultante for idêntica à da política offline, então:

* o prompt contém toda a informação que a política offline usa (paridade);
* o esquema, a interpretação da resposta e a aplicação das decisões estão corretos.

Qualquer diferença aponta um defeito no caminho que será pago com a API.
"""

import json
import re

import pytest

from llm_mas.llm import FunctionLLM
from llm_mas.norms.strategies import DeliberationCase, make_strategy
from llm_mas.scenarios.icu import (
    GOALS_MOTIVATION,
    SUPPRESS_SATISFACTION,
    icu_offline_recommender,
    run_icu,
)
from llm_mas.scenarios.icu_evidence import FINDING_TEXT, NEWS_THRESHOLD, PROFILE_TEXT, news_score

PROFILE_BY_TEXT = {v: k for k, v in PROFILE_TEXT.items()}
BLOCK_RE = re.compile(
    r"ALERTA (?P<pid>P\d+) \(diagnóstico de base: (?P<profile>[^)]*\)?[^)]*)\) — normas [^,]*(?:, [^,]*)*?, "
    r"disparado pela leitura da iteração \d+: (?P<vitals>[^\n]+)")


def parse_blocks(prompt: str) -> dict[str, dict]:
    """Reconstrói, a partir do texto, o que cada política offline usa."""
    out = {}
    for block in prompt.split("ALERTA ")[1:]:
        block = "ALERTA " + block
        pid = block.split()[1]
        profile_text = block.split("diagnóstico de base: ", 1)[1].split(") — normas", 1)[0]
        vitals_text = block.split("disparado pela leitura da iteração ", 1)[1].split(": ", 1)[1].split("\n", 1)[0]
        vitals = {k: float(v) for k, v in (kv.split("=") for kv in vitals_text.split(", "))}
        bedside = block.split("Avaliação à beira-leito: ", 1)[1].split("\n", 1)[0].rstrip(".").split("; ")
        findings = {}
        for name, (present, absent) in FINDING_TEXT.items():
            assert (present in bedside) != (absent in bedside), (name, bedside)
            findings[name] = present in bedside
        nums = re.search(r"Recompensa por cumprir: (\d+(?:\.\d+)?); sanção se a violação for detectada: (\d+(?:\.\d+)?); "
                         r"probabilidade de a auditoria detectar a violação: (\d+(?:\.\d+)?)", block)
        out[pid] = {"profile": PROFILE_BY_TEXT[profile_text], "vitals": vitals, "findings": findings,
                    "numbers": tuple(float(x) for x in nums.groups()) if nums else None}
    return out


def believes_real(info: dict) -> bool:
    return news_score(info["vitals"], info["profile"], info["findings"]) >= NEWS_THRESHOLD


# --------------------------------------------------------------------------
# Fase 2: deliberação (cumprir ou violar)
# --------------------------------------------------------------------------
def strategy_emulating_llm(strategy_name: str) -> FunctionLLM:
    strategy = make_strategy(strategy_name)

    def fn(system, prompt, schema):
        assert schema and "decisions" in schema["properties"]
        decisions = []
        for pid, info in parse_blocks(prompt).items():
            reward, sanction, detection = info["numbers"]
            real = believes_real(info)
            gain = -GOALS_MOTIVATION["segurança do paciente"] if real else SUPPRESS_SATISFACTION
            d = strategy.decide(DeliberationCase(("x",), reward, sanction, detection, gain))
            decisions.append({"patient": pid, "believes_real": real, "comply": d.comply, "justification": d.reason})
        return {"decisions": decisions}

    return FunctionLLM(fn)


PHASE2_KEYS = ("false_alarms", "sensitivity", "mean_latency", "suppressions", "justified_suppressions",
               "harmful_suppressions", "violations_true", "violations_detected", "harm_events",
               "social_contribution", "individual_satisfaction")


@pytest.mark.parametrize("strategy", ["social", "rebellious", "selfish", "pressured", "opportunistic"])
@pytest.mark.parametrize("detection", [0.3, 1.0])
def test_llm_deliberation_path_equals_strategy(strategy, detection):
    kw = {"adaptive": False, "seed": 1, "iterations": 120, "detection": detection}
    offline = run_icu(None, compliance=strategy, **kw)
    via_llm = run_icu(None, compliance="llm", compliance_llm=strategy_emulating_llm(strategy), **kw)
    for k in PHASE2_KEYS:
        assert via_llm.result.metrics[k] == offline.result.metrics[k], k
    strip = lambda ds: [(d["iteration"], d["patient"], d["comply"], d["believes_real"]) for d in ds]  # noqa: E731
    assert strip(via_llm.env.deliberations) == strip(offline.env.deliberations)
    assert via_llm.result.metrics["deliberation_defaults"] == 0 and via_llm.result.metrics["llm_failures"] == 0


def test_llm_deliberation_with_sanction_scale_equals_strategy():
    kw = {"adaptive": False, "seed": 2, "iterations": 120, "detection": 0.3, "sanction_scale": 3.0}
    offline = run_icu(None, compliance="pressured", **kw)
    via_llm = run_icu(None, compliance="llm", compliance_llm=strategy_emulating_llm("pressured"), **kw)
    assert via_llm.result.metrics["suppressions"] == offline.result.metrics["suppressions"] == 0


# --------------------------------------------------------------------------
# Fase 1: agente de decisão e recomendador
# --------------------------------------------------------------------------
def news_emulating_llm() -> FunctionLLM:
    def fn(system, prompt, schema):
        assert schema and "assessments" in schema["properties"]
        return {"assessments": [{"patient": pid, "true_alarm": believes_real(info), "priority": "alta",
                                 "justification": "NEWS2"} for pid, info in parse_blocks(prompt).items()]}

    return FunctionLLM(fn)


def test_llm_decision_path_equals_news_policy():
    offline = run_icu(None, adaptive=True, seed=0)
    via_llm = run_icu(None, adaptive=True, seed=0, decision_llm=news_emulating_llm())
    keys = ("false_alarms", "verdict_accuracy", "verdict_sensitivity", "verdict_specificity", "mean_latency",
            "recognition_latency", "wrong_labels_at_review")
    for k in keys:
        assert via_llm.result.metrics[k] == offline.result.metrics[k], k
    assert via_llm.result.metrics["decision_defaults"] == 0


def heuristic_emulating_recommender() -> FunctionLLM:
    def fn(system, prompt, schema):
        if schema is None:
            return "auditoria"
        assert "proposals" in schema["properties"]
        evidence = json.loads(prompt.split("Evidências (JSON):\n", 1)[1].split("\n\n", 1)[0])
        proposals = icu_offline_recommender(None, evidence, evidence["iteration"])
        return {"proposals": [{
            "base_norm_id": p.base_norm_id, "scope_field": p.scope_field or "", "scope_value": p.scope_value or "",
            "parameters": [{"name": k, "value": v} for k, v in p.parameters.items()],
            "persistence": p.persistence or 0, "rationale": p.rationale} for p in proposals]}

    return FunctionLLM(fn)


def test_llm_recommender_path_equals_heuristic():
    offline = run_icu(None, adaptive=True, seed=0)
    via_llm = run_icu(heuristic_emulating_recommender(), adaptive=True, seed=0, decision_llm=None, validator_llm=None)
    assert via_llm.result.metrics["false_alarms"] == offline.result.metrics["false_alarms"]
    hist = lambda run: [(c.iteration, c.norm_id, c.status, c.after.parameters if c.after else None,  # noqa: E731
                         c.after.persistence if c.after else None) for c in run.env.norms.history]
    assert hist(via_llm) == hist(offline)
