"""Regressões dos problemas apontados na revisão independente do código."""

from llm_mas.core import Action, Agent, Environment, Perception, Simulation
from llm_mas.llm import FunctionLLM
from llm_mas.llm.parsing import format_action
from llm_mas.norms import Condition, Deontic, Norm, NormKnowledgeBase, NormProposal
from llm_mas.scenarios.icu import run_icu
from llm_mas.scenarios.marketplace import build_marketplace, parse_command
from llm_mas.scenarios.project import ProjectEnv, ScenarioGenerator, project_norms, run_project


class Readings(Environment):
    def __init__(self, values):
        super().__init__()
        self.values = values

    def facts(self):
        return [{"id": "P1", "x": self.values[self.iteration - 1]}]


class Alerter(Agent):
    def __init__(self):
        super().__init__("Al", "alerting")

    def analyze_and_plan(self, p: Perception):
        return [Action(self.id, "alert", {"subject": o.subject}) for o in self.env.monitor.pending_for(self)]


def general_norm(**kw):
    return Norm("N", "x < min", Deontic.OBLIGATION, "alerting", target=Condition.all(("type", "==", "alert")),
                activation=Condition.all(("x", "<", "$min")), parameters={"min": 90}, deadline=2, **kw)


def test_specific_norm_added_mid_episode_does_not_realarm():
    env = Readings([87] * 8)
    kb = NormKnowledgeBase([general_norm()])
    env.use_norms(kb)
    env.register(Alerter())
    sim = Simulation(env, 8)

    def add_override(t, actions):
        if t == 2:
            kb.put(NormProposal("N", {"min": 88}, persistence=2, scope_field="id", scope_value="P1").build(kb),
                   t, "", "auto")

    sim.on_iteration = add_override
    result = sim.run()
    assert [a.iteration for a in result.actions if a.type == "alert"] == [2]


def test_rearm_reopens_while_condition_persists():
    env = Readings([5] * 7)
    env.use_norms(NormKnowledgeBase([general_norm(rearm=True, sanction=1)]))

    class Idle(Agent):
        def analyze_and_plan(self, p):
            return []

    env.register(Idle("Al", "alerting"))
    result = Simulation(env, 7).run()
    assert [v.iteration for v in result.violations] == [3, 5, 7]  # uma por prazo enquanto persistir


def test_persistence_zero_keeps_current_value():
    kb = NormKnowledgeBase([general_norm()])
    kb.put(NormProposal("N", {"min": 88}, persistence=2, scope_field="id", scope_value="P1").build(kb), 1, "", "a")
    again = NormProposal("N", {"min": 87}, persistence=None, scope_field="id", scope_value="P1").build(kb)
    assert again.persistence == 2 and again.parameters == {"min": 87}


def test_icu_evidence_is_versioned_and_heuristic_converges():
    run = run_icu(iterations=120, seed=0)
    evidence = run.env.adaptation_evidence()
    changed = {pid: ev for pid, info in evidence["patients"].items()
               for base, ev in info["alarm_norms"].items() if ev["norm_in_force"] != base}
    assert changed  # houve adaptação por paciente
    for ev in changed.values():
        assert ev["last_change_iteration"] is not None
        assert ev["false_alarms_since_change"] <= ev["false_alarms_total"]


def test_ineffective_assignment_does_not_fulfill_backlog_obligation():
    """Gerente que atribui tudo ao Dev2 (que sai na it. 9) não pode ficar sem violações."""
    def all_to_dev2(system, prompt, schema):
        if "manager" not in system:
            return ""
        tasks = [line.split()[0] for line in prompt.splitlines() if line.startswith("T") and " todo " in line]
        return "".join(format_action("Dev2", f"assign {t}") for t in tasks)

    result, env = run_project(FunctionLLM(all_to_dev2), seed=0, iterations=40,
                              scenario=ScenarioGenerator(None, 0).generate())
    assert result.metrics["completed_at"] is None
    assert sum(v.norm_id == "PM-ASSIGN-BACKLOG" for v in result.violations) > 10


def test_batched_assignments_in_one_message_have_no_effect_and_are_reported():
    env = ProjectEnv(ScenarioGenerator(None, 0).generate(), 0)
    env.use_norms(NormKnowledgeBase(project_norms()))
    from llm_mas.scenarios.project import DeveloperAgent, ProjectManagerAgent

    env.register(ProjectManagerAgent("PM"))
    env.register(DeveloperAgent("Dev1", {"backend": 1.0}, "PM"))
    env.iteration = 1
    env.apply_round([Action.send("PM", "Dev1", "assign T1, assign T4", iteration=1),
                     Action.send("PM", "Dev1", "assign T999")])
    assert env.tasks["T1"].assignee is None
    notices = env.pop_notices("PM")
    assert any("não é só o comando" in n for n in notices) and any("T999 não existe" in n for n in notices)


def test_marketplace_commands_are_case_insensitive_and_failures_are_notified():
    assert parse_command("confirm_SALE: 30") == ("Confirm_sale", 30.0)
    env = build_marketplace(FunctionLLM(
        lambda s, p, schema: format_action("Agent4", "Confirm_sale: 30") if "agente Agent1" in s else ""), seed=0)
    Simulation(env, 1).run()
    assert any("não gerou venda" in n for n in env.pop_notices("Agent1"))


def test_llm_agent_sees_notices_in_next_prompt():
    seen = []

    def llm(system, prompt, schema):
        if "agente Agent1" in system:
            seen.append(prompt)
            return format_action("Agent4", "Confirm_sale: 30")
        return ""

    env = build_marketplace(FunctionLLM(llm), seed=0)
    Simulation(env, 2).run()
    agent1_prompts = seen
    assert any("Avisos do ambiente" in p and "não gerou venda" in p for p in agent1_prompts)
