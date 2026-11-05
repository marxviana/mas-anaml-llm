"""Invariantes da fase 2: determinismo, pareamento, ordem e contabilidade."""

import pytest

from llm_mas.core import Simulation
from llm_mas.norms import NormKnowledgeBase
from llm_mas.norms.strategies import make_strategy
from llm_mas.scenarios.icu import AlertingAgent, DecisionAgent, ICUEnv, MonitoringAgent, icu_norms, make_patients, run_icu

STRATEGIES = ["social", "rebellious", "selfish", "pressured", "opportunistic"]


def test_deterministic():
    a = run_icu(None, adaptive=False, seed=3, compliance="selfish", detection=0.3)
    b = run_icu(None, adaptive=False, seed=3, compliance="selfish", detection=0.3)
    assert a.result.metrics == b.result.metrics
    assert [e.detected for e in a.result.norm_events] == [e.detected for e in b.result.norm_events]


def test_paired_conditions_see_the_same_patients_readings_and_findings():
    runs = [run_icu(None, adaptive=False, seed=4, compliance=s, detection=d)
            for s in STRATEGIES for d in (0.3, 1.0)] + [run_icu(None, adaptive=True, seed=4)]
    ref = runs[0].env
    for run in runs[1:]:
        for pid, p in run.env.patients.items():
            assert p.readings == ref.patients[pid].readings and p.onset == ref.patients[pid].onset
            assert p.artifacts == ref.patients[pid].artifacts
        for t in (5, 50, 100):
            assert run.env._bedside_findings("P1", t) == ref._bedside_findings("P1", t)


def _run_with_order(order, seed=5):
    env = ICUEnv(make_patients(12, 120, seed), seed=seed)
    env.use_norms(NormKnowledgeBase(icu_norms()), 0.3)
    ids = list(env.patients)
    agents = {"Monitor1": MonitoringAgent("Monitor1", ids[:6]), "Monitor2": MonitoringAgent("Monitor2", ids[6:]),
              "Alerting": AlertingAgent("Alerting", "Decision", make_strategy("opportunistic")),
              "Decision": DecisionAgent("Decision")}
    for name in order:
        env.register(agents[name])
    return Simulation(env, 120).run().metrics


def test_order_invariance_with_deliberation():
    a = _run_with_order(["Monitor1", "Monitor2", "Alerting", "Decision"])
    b = _run_with_order(["Decision", "Alerting", "Monitor2", "Monitor1"])
    assert a == b


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_accounting_identities(strategy):
    run = run_icu(None, adaptive=False, seed=6, compliance=strategy, detection=0.3)
    m, env = run.result.metrics, run.env
    assert m["suppressions"] == m["justified_suppressions"] + m["harmful_suppressions"]
    # dano: no máximo um por episódio, só se a supressão atrasou o reconhecimento, cobrado na confirmação
    delay = env.confirm_delay
    harmed = {(d["patient"], env.patients[d["patient"]].onset) for d in env.deliberations
              if not d["comply"] and d["truth"] and env._episode_harmed(d)}
    discovered = {(d["patient"], env.patients[d["patient"]].onset) for d in env.deliberations
                  if not d["comply"] and d["truth"] and env._episode_harmed(d)
                  and d["reading_iteration"] + delay <= env.iteration}
    assert m["harmed_episodes"] == len(harmed) and m["harm_events"] == len(discovered)
    assert m["harm_events"] <= m["harmed_episodes"] <= m["harmful_suppressions"]
    # toda obrigação suprimida expira como violação (nenhum outro alarme a "cumpre")
    expired = sum(len(d["norms"]) for d in env.deliberations if not d["comply"] and d["reading_iteration"] + 2 <= env.iteration)
    assert m["violations_true"] == expired
    assert m["violations_detected"] <= m["violations_true"]
    # nenhuma decisão sobre a norma crítica regimentada
    assert all("ICU-CRITICAL" not in d["norms"] for d in env.deliberations)
    # alarmes soados = obrigações cumpridas; nenhuma supressão vira alarme
    suppressed = {(d["patient"], d["reading_iteration"]) for d in env.deliberations if not d["comply"]}
    raised = {(a["patient"], a["reading_iteration"]) for a in env.alarms}
    assert not (suppressed & raised) or all("ICU-CRITICAL" in a["norms"] for a in env.alarms
                                            if (a["patient"], a["reading_iteration"]) in suppressed)


def test_detection_rate_matches_probability():
    viol = det = 0
    for seed in range(6):
        events = [e for e in run_icu(None, adaptive=False, seed=seed, compliance="rebellious",
                                     detection=0.3).result.norm_events if e.kind == "violation"]
        viol += len(events)
        det += sum(e.detected for e in events)
    assert 0.25 < det / viol < 0.35
    full = [e for e in run_icu(None, adaptive=False, seed=0, compliance="rebellious", detection=1.0).result.norm_events
            if e.kind == "violation"]
    assert all(e.detected for e in full)


def test_compliant_deliberation_equals_phase1_static():
    """Um agente deliberativo que sempre cumpre não pode mudar nada em relação à fase 1."""
    base = run_icu(None, adaptive=False, seed=7).result.metrics
    social = run_icu(None, adaptive=False, seed=7, compliance="social", detection=0.3).result.metrics
    for k in ("false_alarms", "sensitivity", "specificity", "mean_latency", "verdict_accuracy"):
        assert base[k] == social[k], k
