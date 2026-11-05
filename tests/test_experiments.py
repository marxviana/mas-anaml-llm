import json

import pytest

from llm_mas.cli import load_dotenv
from llm_mas.experiments import run_comparison
from llm_mas.llm import FunctionLLM
from llm_mas.llm.claude import BudgetExceeded


def fake_llm(system, prompt, schema):
    if schema is None:
        return "relatório de auditoria" if "Auditor" in system else ""
    props = schema["properties"]
    if "proposals" in props:
        return {"proposals": []}
    if "approve" in props:
        return {"approve": True, "issues": []}
    return {"assessments": []}


def test_comparison_pipeline_writes_results_and_report(tmp_path):
    results = run_comparison(FunctionLLM(fake_llm), tmp_path, seeds=[0, 1], icu_iterations=40)
    saved = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert {r["mode"] for r in saved["icu"]} == {"static", "adaptive-oracle", "adaptive-heuristic", "adaptive-llm"}
    assert [(r["mode"], r["seed"]) for r in saved["marketplace"]] == [
        ("offline", 0), ("llm", 0), ("offline", 1), ("llm", 1)]  # pareado por semente
    llm_icu = next(r for r in results["icu"] if r["mode"] == "adaptive-llm")
    assert llm_icu["norm_changes_applied"] == 0 and llm_icu["audit"] == "relatório de auditoria"
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "## UTI (ANA-ML 2.0)" in report and "Sementes pareadas: [0, 1]" in report


def test_unexpected_llm_output_is_recorded_not_fatal(tmp_path):
    """Uma tarefa inexistente citada pelo gerente LLM não pode derrubar a comparação."""
    def bad_pm(system, prompt, schema):
        return "\\begin{action}Dev1: assign T999\\end{action}" if "manager" in system else ""

    results = run_comparison(FunctionLLM(bad_pm), tmp_path, scenarios=["project"], seeds=[0])
    llm_run = next(r for r in results["project"] if r["mode"] == "llm")
    assert "error" not in llm_run and llm_run["finished"] == 0
    assert llm_run["viol:PM-ASSIGN-BACKLOG"] > 25  # a obrigação reabre enquanto as tarefas seguem sem dono


def test_failed_run_is_excluded_from_paired_table(tmp_path):
    calls = {"n": 0}

    def flaky(system, prompt, schema):
        calls["n"] += 1
        raise RuntimeError("resposta malformada")

    results = run_comparison(FunctionLLM(flaky), tmp_path, scenarios=["marketplace"], seeds=[0, 1])
    assert all("error" in r for r in results["marketplace"] if r["mode"] == "llm")
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Sementes pareadas: [] (n = 0)" in report and "execução descartada" in report


def test_budget_exceeded_saves_partial_results(tmp_path):
    def broke(system, prompt, schema):
        raise BudgetExceeded("limite atingido")

    with pytest.raises(BudgetExceeded):
        run_comparison(FunctionLLM(broke), tmp_path, scenarios=["marketplace"], seeds=[0])
    saved = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert saved["aborted"] == "limite atingido" and saved["marketplace"][0]["mode"] == "offline"


def test_load_dotenv_does_not_override(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("# comentário\nexport FOO_TEST='abc'\nBAR_TEST=1\n", encoding="utf-8")
    monkeypatch.setenv("BAR_TEST", "já definido")
    monkeypatch.delenv("FOO_TEST", raising=False)
    load_dotenv(env_file)
    import os

    assert os.environ["FOO_TEST"] == "abc" and os.environ["BAR_TEST"] == "já definido"
