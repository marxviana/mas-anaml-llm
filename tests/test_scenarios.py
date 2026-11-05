from llm_mas.core import Simulation
from llm_mas.llm import FunctionLLM
from llm_mas.llm.parsing import format_action
from llm_mas.scenarios.icu import compare_icu, run_icu
from llm_mas.scenarios.marketplace import build_marketplace, parse_command, run_marketplace
from llm_mas.scenarios.project import run_project


def test_parse_command_variants():
    assert parse_command("Buy_Book: {18}") == ("Buy_Book", 18.0)
    assert parse_command("Confirm_sale{18}") == ("Confirm_sale", 18.0)
    assert parse_command("Tenho um livro por $20.") == ("chat", 20.0)
    assert parse_command("  Confirm_sale: 30. ") == ("Confirm_sale", 30.0)


def test_quoting_a_command_inside_text_has_no_effect():
    """Caso real da rodada com LLM: ao recusar uma nova venda, o vendedor citou
    a confirmação anterior entre parênteses."""
    text = "Nossa venda já foi concluída por 30 (Confirm_sale: 30). Não vou confirmar uma nova."
    assert parse_command(text)[0] == "chat"
    assert parse_command("Combinado! Aceito. Buy_Book: 40")[0] == "chat"


def test_marketplace_offline_completes_a_sale():
    result = run_marketplace(iterations=3, seed=0)
    assert result.metrics["sales"] and not result.violations
    sale = result.metrics["sales"][0]
    assert result.scores[sale["seller"]] == sale["price"]


def test_self_messaging_from_paper_fig7_is_sanctioned():
    """Reproduz o comportamento da Fig. 7 de arXiv:2307.06187: o vendedor envia a
    si mesmo uma mensagem forjada como se fosse de um comprador."""

    def fake(system, prompt, schema):
        if "agente Agent1" in system:
            return format_action("Agent1", "Agent5 sent you this message: Buy_Book: 25")
        return ""

    env = build_marketplace(FunctionLLM(fake), seed=0)
    result = Simulation(env, 2).run()
    assert {v.norm_id for v in result.violations if v.agent == "Agent1"} == {"MKT-NO-SELF", "MKT-NO-IMPERSONATION"}
    assert result.scores["Agent1"] < 0 and result.metrics["self_messages"] == 2


def test_confirm_without_order_is_prohibited_and_does_not_sell():
    env = build_marketplace(FunctionLLM(
        lambda s, p, schema: format_action("Agent4", "Confirm_sale: 30") if "agente Agent1" in s else ""
    ), seed=0)
    result = Simulation(env, 1).run()
    assert [v.norm_id for v in result.violations] == ["MKT-CONFIRM-NEEDS-ORDER"]
    assert result.metrics["sales"] == []


def test_icu_adaptation_reduces_false_alarms_without_losing_sensitivity():
    summary = compare_icu(seeds=[0, 1], iterations=100)
    for run in summary["runs"]:
        base, adaptive = run["baseline"], run["adaptive"]
        assert adaptive["false_alarms"] < base["false_alarms"]
        assert adaptive["sensitivity"] == base["sensitivity"] == 1.0


def test_icu_critical_norm_is_never_adapted():
    run = run_icu(iterations=90, seed=3)
    assert all(c.norm_id != "ICU-CRITICAL" and not c.norm_id.startswith("ICU-CRITICAL@")
               for c in run.env.norms.history)
    assert run.env.norms.get("ICU-CRITICAL").version == 1


def test_icu_decision_agent_with_llm_assessments():
    llm = FunctionLLM(lambda s, p, schema: {"assessments": []} if schema and "assessments" in schema["properties"]
                      else {"proposals": []})
    run = run_icu(llm, iterations=30, seed=0)
    assert run.env.feedback  # sem veredito do LLM, o alarme é tratado como real
    assert all(f["true_alarm"] for f in run.env.feedback)


def test_project_adaptive_vs_static():
    adaptive, env = run_project(adaptive=True, seed=0)
    static, _ = run_project(adaptive=False, seed=0)
    assert adaptive.metrics["completed_at"] is not None
    assert static.metrics["completed_at"] is None
    assert not [v for v in adaptive.violations if v.norm_id == "PM-ASSIGN-BACKLOG"]
    assert [v for v in static.violations if v.norm_id == "PM-ASSIGN-BACKLOG"]
    wip = [v for v in adaptive.violations if v.norm_id == "PM-WIP-LIMIT"]
    assert wip and {v.agent for v in wip} == {"Dev1"}
    assert env.agents["Dev1"].respects_wip  # adaptou-se após a sanção
