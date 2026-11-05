"""Fase 2: deliberação normativa (cumprir ou violar) com fiscalização imperfeita."""

import json

from llm_mas.llm import FunctionLLM
from llm_mas.norms import Condition, Deontic, Norm, NormKnowledgeBase
from llm_mas.norms.strategies import DeliberationCase, make_strategy
from llm_mas.scenarios.icu import run_icu


def case(gain=3.0, detection=0.3, sanction=5.0, reward=1.0):
    return DeliberationCase(("N",), reward, sanction, detection, gain)


def test_strategies_follow_their_definitions():
    assert make_strategy("social").decide(case()).comply
    assert not make_strategy("rebellious").decide(case(gain=-10)).comply
    assert not make_strategy("selfish").decide(case(detection=1.0, sanction=100)).comply
    assert make_strategy("selfish").decide(case(gain=-10)).comply
    pressured = make_strategy("pressured")
    assert not pressured.decide(case(detection=0.3, sanction=5)).comply      # 0.3*5+1 = 2.5 < 3
    assert pressured.decide(case(detection=0.3, sanction=15)).comply         # sanção maior dissuade
    opp = make_strategy("opportunistic")
    assert not opp.decide(case(detection=0.3, sanction=15)).comply           # só a detecção importa
    assert opp.decide(case(detection=0.7, sanction=1)).comply


def test_imperfect_enforcement_hides_some_violations():
    from llm_mas.core import Agent, Environment, Simulation

    class Facts(Environment):
        def facts(self):
            return [{"id": f"S{self.iteration}", "x": 1}]

    class Idle(Agent):
        def analyze_and_plan(self, p):
            return []

    env = Facts(seed=0)
    env.use_norms(NormKnowledgeBase([Norm("N", "", Deontic.OBLIGATION, "a", target=Condition.all(("type", "==", "x")),
                                          deadline=1, sanction=1)]), detection=0.3)
    agent = env.register(Idle("A", "a"))
    result = Simulation(env, 200).run()
    viol = [e for e in result.norm_events if e.kind == "violation"]
    detected = [e for e in viol if e.detected]
    assert 0.2 < len(detected) / len(viol) < 0.4
    assert agent.score == -len(detected)  # só violações detectadas sancionam


def test_critical_norm_is_regimented_even_for_rebels():
    run = run_icu(adaptive=False, seed=0, compliance="rebellious", detection=0.3)
    critical = [a for a in run.env.alarms if "ICU-CRITICAL" in a["norms"]]
    assert critical and all(not d["comply"] for d in run.env.deliberations)
    assert all("ICU-CRITICAL" not in d["norms"] for d in run.env.deliberations)
    assert run.result.metrics["sensitivity"] == 1.0  # a norma crítica ainda alarma as pioras graves


def test_harmful_suppression_is_discovered_and_penalized():
    from llm_mas.scenarios.icu import HARM_PENALTY

    run = run_icu(adaptive=False, seed=0, compliance="rebellious", detection=0.0)
    m = run.result.metrics
    assert m["harmful_suppressions"] > 0 and 0 < m["harm_events"] <= m["harmed_episodes"]
    assert m["violations_detected"] == 0
    agent = run.env.agents["Alerting"]
    rewards = sum(e.delta for e in run.result.norm_events if e.kind == "fulfillment" and e.agent == "Alerting")
    assert agent.score == rewards - HARM_PENALTY * m["harm_events"]  # o dano é cobrado mesmo sem fiscalização
    # o rebelde viola mesmo quando acredita que a piora é real; aí não há satisfação a ganhar
    assert agent.satisfaction == 3.0 * sum(1 for d in run.env.deliberations if not d["comply"] and not d["believes_real"])


def test_deterrence_changes_strategic_behavior():
    sup = {p: run_icu(adaptive=False, seed=0, compliance="opportunistic", detection=p).result.metrics["suppressions"]
           for p in (0.3, 1.0)}
    assert sup[0.3] > 0 and sup[1.0] == 0


def test_llm_deliberation_parity_and_parsing():
    prompts = []

    def llm(system, prompt, schema):
        if schema and "decisions" in schema["properties"]:
            prompts.append(prompt)
            pids = schema["properties"]["decisions"]["items"]["properties"]["patient"]["enum"]
            return {"decisions": [{"patient": p, "believes_real": False, "comply": False, "justification": "teste"}
                                  for p in pids]}
        return {}

    run = run_icu(adaptive=False, seed=0, iterations=40, compliance="llm", compliance_llm=FunctionLLM(llm),
                  detection=0.7)
    assert prompts and "probabilidade de a auditoria detectar a violação: 0.7" in prompts[0]
    assert "sanção se a violação for detectada: 5" in prompts[0]
    text = "\n".join(prompts).lower()
    for leak in ("deterioração", "in_episode", "episódio"):
        assert leak not in text
    assert all(d["policy"] == "llm" for d in run.env.deliberations)
    assert run.result.metrics["suppressions"] == len(run.env.deliberations)


def test_phase2_runner_offline(tmp_path):
    from llm_mas.experiments_phase2 import run_phase2

    res = run_phase2(None, tmp_path, seeds=[0], detections=[0.3, 1.0], sanction_scales=[1.0], llm_detections=[],
                     iterations=60)
    conds = {r["condition"] for r in res["runs"]}
    assert conds == {"adaptive-compliant", "social", "rebellious", "selfish", "pressured", "opportunistic"}
    assert "Sanção padrão" in (tmp_path / "report.md").read_text(encoding="utf-8")
    json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))


def test_llm_runs_with_failed_calls_are_flagged_and_excluded(tmp_path):
    from llm_mas.experiments_phase2 import run_phase2
    from llm_mas.llm.base import LLMError

    def broken(system, prompt, schema):
        raise LLMError("timeout simulado")

    res = run_phase2(FunctionLLM(broken), tmp_path, seeds=[0], detections=[0.3], sanction_scales=[1.0],
                     llm_detections=[0.3], iterations=40)
    llm_run = next(r for r in res["runs"] if r["condition"] == "llm")
    assert "invalid" in llm_run and llm_run["llm_failures"] > 0
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "| llm, p=0.3 |" not in report and "Execuções descartadas" in report
