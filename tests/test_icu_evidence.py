"""Evidências imperfeitas na UTI: o agente de decisão não pode ler o estado oculto."""

import random

from llm_mas.llm import FunctionLLM
from llm_mas.scenarios.icu import DETERIORATION, PROFILES, run_icu
from llm_mas.scenarios.icu_evidence import (
    FINDINGS,
    bayes_posterior,
    draw_findings,
    finding_probability,
    news_score,
)


def test_findings_are_noisy_and_informative():
    rng = random.Random(0)
    stable = [draw_findings(rng, "stable", 0, False) for _ in range(2000)]
    sick = [draw_findings(rng, "stable", 6, False) for _ in range(2000)]
    for name in FINDINGS:
        p_stable = sum(f[name] for f in stable) / 2000
        p_sick = sum(f[name] for f in sick) / 2000
        assert 0 < p_stable < p_sick < 1  # nem perfeito, nem inútil
    assert finding_probability("dispneia", "copd", 0) == 0.5  # dispneia basal na DPOC


def test_decision_prompt_does_not_leak_ground_truth():
    prompts = []

    def llm(system, prompt, schema):
        if schema and "assessments" in schema["properties"]:
            prompts.append(prompt)
            return {"assessments": []}
        return {"proposals": []} if schema else ""

    run_icu(None, iterations=60, seed=0, decision_llm=FunctionLLM(llm))
    assert prompts
    text = "\n".join(prompts).lower()
    for leak in ("deterioração", "estável", "in_episode", "true", "episódio"):
        assert leak not in text


def test_same_alarm_gets_same_findings_across_modes():
    a = run_icu(None, adaptive=False, iterations=40, seed=1).env.alarms
    b = run_icu(None, adaptive=True, iterations=40, seed=1, decision_policy="oracle").env.alarms
    findings_a = {(x["patient"], x["reading_iteration"]): x["findings"] for x in a}
    common = [(x["patient"], x["reading_iteration"]) for x in b if (x["patient"], x["reading_iteration"]) in findings_a]
    assert common and all(findings_a[k] == next(x["findings"] for x in b
                                                 if (x["patient"], x["reading_iteration"]) == k) for k in common)


def test_news_baseline_and_bayes_reference():
    calm = {"spo2": 97, "hr": 78, "sbp": 120, "rr": 16}
    sick = {"spo2": 88, "hr": 128, "sbp": 96, "rr": 26}
    none = {k: False for k in (*FINDINGS, "sinal_artefato")}
    assert news_score(calm, "stable", none) == 0
    assert news_score(sick, "stable", none) >= 5
    assert news_score({**calm, "spo2": 89.5, "rr": 21}, "copd", none) < news_score({**calm, "spo2": 89.5}, "stable", none)
    args = ("stable", 0.2, 10, 0.05, PROFILES, DETERIORATION)
    assert bayes_posterior(calm, none, *args) < 0.1 < 0.9 < bayes_posterior(sick, none, *args)


def test_wrong_verdicts_reach_adaptation_but_not_metrics():
    news = run_icu(None, iterations=120, seed=0).result.metrics
    oracle = run_icu(None, iterations=120, seed=0, decision_policy="oracle").result.metrics
    assert oracle["verdict_accuracy"] == 1.0 and oracle["wrong_labels_at_review"] == 0
    assert news["verdict_accuracy"] < 1.0 and news["wrong_labels_at_review"] > 0
    assert news["bayes_accuracy"] > news["news_accuracy"]  # o teto fica acima da linha de base
