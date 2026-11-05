"""Comparação sem LLM × com LLM nos três cenários.

Cada comparação muda uma única variável — quem raciocina (política
determinística ou LLM) — mantendo o resto igual, e é pareada por semente
(mesmos pacientes, leituras, cenário de projeto e sorteios do ambiente):

* ``marketplace`` — os mesmos 5 agentes, com política heurística ou com o LLM;
* ``icu``         — normas estáticas; adaptação com rótulos perfeitos (oráculo,
  referência); adaptação heurística (recomendador heurístico + decisão NEWS2);
  ``adaptive-llm`` troca só o recomendador pelo LLM; com ``llm_decision=True``,
  ``adaptive-llm-decision`` troca só o agente de decisão. O validador é
  determinístico (``llm_validator=True`` adiciona a revisão do LLM);
* ``project``     — o mesmo cenário com o gerente heurístico ou com o gerente LLM.

Cada execução é gravada em ``out_dir/results.json`` assim que termina; as
chamadas ao LLM ficam em ``out_dir/transcripts.jsonl``.
"""

from __future__ import annotations

import json
import statistics
import traceback
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from llm_mas.core.simulation import SimulationResult
from llm_mas.llm.base import LLMClient
from llm_mas.llm.base import BudgetExceeded, NoAnswer

SCENARIOS = ("marketplace", "icu", "project")
Emit = Callable[[dict[str, Any]], None]


def _violations(result: SimulationResult) -> dict[str, int]:
    return dict(Counter(v.norm_id for v in result.violations))


def _guarded(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Qualquer falha em uma execução é registrada (com o traceback) sem perder
    as demais; o estouro do orçamento ou o fim dos créditos interrompe tudo."""
    try:
        return fn()
    except BudgetExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 — uma resposta inesperada do LLM não pode derrubar a comparação
        return {"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}


def _tag(llm: LLMClient | None, tag: str) -> None:
    if llm is not None and hasattr(llm, "tag"):
        llm.tag = tag


# --------------------------------------------------------------------------
def marketplace_runs(llm: LLMClient, seeds: list[int], emit: Emit, iterations: int = 3) -> None:
    from llm_mas.scenarios.marketplace import run_marketplace

    def summary(result: SimulationResult) -> dict[str, Any]:
        m = result.metrics
        prices = [s["price"] for s in m["sales"]]
        return {
            "sales": len(prices),
            "mean_price": round(statistics.mean(prices), 2) if prices else None,
            "unsold_sellers": len(m["unsold_sellers"]),
            "buyers_without_book": len(m["buyers_without_book"]),
            "messages": m["messages"],
            "self_messages": m["self_messages"],
            "llm_failures": m["llm_failures"],
            "violations": _violations(result),
            "transcript": [f"[it {a.iteration}] {a.agent} → {a.data['receiver']}: {a.data['content']}"
                           for a in result.actions if a.type == "send"],
        }

    for s in seeds:
        emit({"mode": "offline", "seed": s, **summary(run_marketplace(None, iterations, seed=s))})
        _tag(llm, f"marketplace/seed{s}")
        emit({"mode": "llm", "seed": s, **_guarded(lambda: summary(run_marketplace(llm, iterations, seed=s)))})


def icu_runs(llm: LLMClient, seeds: list[int], emit: Emit, iterations: int = 120, patients: int = 12,
             llm_decision: bool = False, llm_validator: bool = False) -> None:
    from llm_mas.scenarios.icu import run_icu

    def summary(run, audit: bool = False) -> dict[str, Any]:
        statuses = Counter(c.status for c in run.env.norms.history)
        out = {
            **run.result.metrics,
            "norm_changes_applied": statuses["applied"],
            "norm_changes_rejected_validation": statuses["rejected_validation"],
            "norm_changes_rejected_supervisor": statuses["rejected_supervisor"],
            "norm_changes": [f"it {c.iteration} {c.norm_id} {c.after.parameters if c.after else ''} "
                             f"[{c.status}]: {c.rationale}" for c in run.env.norms.history],
            "violations": _violations(run.result),
        }
        if run.processor is not None:
            out["llm_failures"] += sum(c.failures for c in (run.processor.recommender, run.processor.validator,
                                                            run.processor.auditor))
        if audit and run.processor is not None:
            out["audit"] = run.processor.auditor.audit(run.env.norms, run.result.norm_events,
                                                       run.result.metrics).narrative
        return out

    kw = {"iterations": iterations, "patients": patients}
    for s in seeds:
        emit({"mode": "static", "seed": s, **summary(run_icu(None, adaptive=False, seed=s, **kw))})
        emit({"mode": "adaptive-oracle", "seed": s,
              **summary(run_icu(None, adaptive=True, seed=s, decision_policy="oracle", **kw))})
        emit({"mode": "adaptive-heuristic", "seed": s, **summary(run_icu(None, adaptive=True, seed=s, **kw))})
        _tag(llm, f"icu/seed{s}/recommender")
        emit({"mode": "adaptive-llm", "seed": s, **_guarded(lambda: summary(run_icu(
            llm, adaptive=True, seed=s, decision_llm=None,
            validator_llm=llm if llm_validator else None, **kw), audit=True))})
        if llm_decision:  # só o agente de decisão muda em relação a adaptive-heuristic
            _tag(llm, f"icu/seed{s}/decision")
            emit({"mode": "adaptive-llm-decision", "seed": s, **_guarded(lambda: summary(run_icu(
                None, adaptive=True, seed=s, decision_llm=llm, **kw)))})


def project_runs(llm: LLMClient, seeds: list[int], emit: Emit, iterations: int = 60) -> None:
    from llm_mas.scenarios.project import ScenarioGenerator, run_project

    def summary(result: SimulationResult) -> dict[str, Any]:
        m = result.metrics
        finished = m["completed_at"] is not None
        return {
            "finished": int(finished),
            # execuções não concluídas são censuradas no limite de iterações
            "completion_censored": m["completed_at"] if finished else iterations,
            "tasks_done": m["tasks_done"], "tasks_total": m["tasks_total"],
            "remaining_effort": m["remaining_effort"], "planned_iterations": m["planned_iterations"],
            "llm_failures": m["llm_failures"],
            "violations": _violations(result),
        }

    for s in seeds:
        # o cenário é regenerado a cada execução porque as tarefas são mutadas durante a simulação
        result, _ = run_project(None, iterations=iterations, seed=s, scenario=ScenarioGenerator(None, s).generate())
        emit({"mode": "offline", "seed": s, **summary(result)})
        _tag(llm, f"project/seed{s}")
        emit({"mode": "llm", "seed": s, **_guarded(lambda: summary(run_project(
            llm, iterations=iterations, seed=s, scenario=ScenarioGenerator(None, s).generate())[0]))})



# --------------------------------------------------------------------------
# Dry-run: conta e mede as chamadas sem usar a API
# --------------------------------------------------------------------------
# Tokens por chamada observados nas rodadas reais com claude-opus-5-5 (effort medium).
# Servem de teto para a saída: com effort low o modelo pensa e escreve menos.
OBSERVED_OUTPUT_TOKENS = {"marketplace": 424, "project": 1426, "icu-recommender": 1279,
                          "icu-validator": 608, "icu-auditor": 4553}
# agente de decisão, medido com effort low: ~145 tokens por alarme avaliado (arredondado para cima)
DECISION_OUTPUT_PER_ALARM = 160
CHARS_PER_TOKEN = 1.6  # abaixo da menor razão medida (1,64 na deliberação): estimativa conservadora
# tokens que o esquema de saída estruturada acrescenta à entrada (medidos com count_tokens)
SCHEMA_OVERHEAD = {"icu-decision": 400, "icu-deliberation": 420, "icu-recommender": 540, "icu-validator": 240}


class DryRunLLM:
    """Registra cada chamada (categoria e tamanho do prompt) e não responde:
    os componentes recorrem à política offline, como numa falha pontual, o que
    mantém a simulação andando com trajetórias realistas."""

    def __init__(self) -> None:
        import threading

        self.tag = ""
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def _record(self, system: str, prompt: str) -> None:
        scenario = self.tag.split("/")[0]
        if "agente de alerta" in system:
            kind = "icu-deliberation"
        elif scenario == "icu":
            kind = ("icu-auditor" if "Auditor" in system else "icu-validator" if "Validator" in system
                    else "icu-decision" if "agente de decisão" in system else "icu-recommender")
        else:
            kind = scenario
        with self._lock:
            self.calls.append({"tag": self.tag, "kind": kind, "chars": len(system) + len(prompt),
                               "alarms": prompt.count("ALERTA ")})
        raise NoAnswer("dry-run")

    def generate(self, system: str, prompt: str) -> str:
        self._record(system, prompt)
        return ""

    def generate_json(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        self._record(system, prompt)
        return {}


def estimate_cost(dry: DryRunLLM, price_in: float, price_out: float) -> dict[str, Any]:
    by_kind: dict[str, dict[str, float]] = {}
    for c in dry.calls:
        k = by_kind.setdefault(c["kind"], {"calls": 0, "input_tokens": 0.0, "output_tokens": 0.0})
        k["calls"] += 1
        k["input_tokens"] += c["chars"] / CHARS_PER_TOKEN + SCHEMA_OVERHEAD.get(c["kind"], 0)
        k["output_tokens"] += (DECISION_OUTPUT_PER_ALARM * c["alarms"] if c["kind"] in ("icu-decision", "icu-deliberation")
                               else OBSERVED_OUTPUT_TOKENS.get(c["kind"], 1000))
    for k in by_kind.values():
        k["cost_usd"] = (k["input_tokens"] * price_in + k["output_tokens"] * price_out) / 1_000_000
    total = sum(k["cost_usd"] for k in by_kind.values())
    return {"by_kind": by_kind, "calls": len(dry.calls), "cost_usd": total}


# --------------------------------------------------------------------------
def estimate_calls(scenarios: list[str], seeds: list[int], icu_iterations: int, llm_decision: bool,
                   llm_validator: bool = False, adapt_every: int = 15) -> int:
    calls = 0
    if "marketplace" in scenarios:
        calls += len(seeds) * 5 * 3
    if "icu" in scenarios:
        reviews = (icu_iterations - 1) // adapt_every
        per_seed = reviews * (1 + (3 if llm_validator else 0)) + 1  # recomendações (+ validações) + auditoria
        calls += len(seeds) * (per_seed + (icu_iterations if llm_decision else 0))
    if "project" in scenarios:
        calls += len(seeds) * 25
    return calls


def run_comparison(llm: LLMClient, out_dir: str | Path, scenarios: list[str] | None = None,
                   seeds: list[int] | None = None, icu_iterations: int = 120, llm_decision: bool = False,
                   llm_validator: bool = False) -> dict[str, Any]:
    scenarios = list(scenarios or SCENARIOS)
    seeds = seeds or [0, 1, 2]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {"config": {"scenarios": scenarios, "seeds": seeds, "icu_iterations": icu_iterations,
                                          "llm_decision": llm_decision, "llm_validator": llm_validator}}

    def save() -> None:
        if hasattr(llm, "usage"):
            results["usage"] = llm.usage()
        (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    def emitter(name: str) -> Emit:
        results[name] = []

        def emit(run: dict[str, Any]) -> None:
            results[name].append(run)
            save()

        return emit

    steps = {
        "marketplace": lambda emit: marketplace_runs(llm, seeds, emit),
        "icu": lambda emit: icu_runs(llm, seeds, emit, icu_iterations, llm_decision=llm_decision,
                                     llm_validator=llm_validator),
        "project": lambda emit: project_runs(llm, seeds, emit),
    }
    try:
        for name in scenarios:
            print(f"→ {name}...", flush=True)
            steps[name](emitter(name))
    except BudgetExceeded as exc:
        results["aborted"] = str(exc)
        raise
    finally:
        save()
        (out / "report.md").write_text(render_report(results), encoding="utf-8")
    return results


# --------------------------------------------------------------------------
def _paired(runs: list[dict[str, Any]], modes: list[str]) -> tuple[list[int], dict[str, dict[int, dict]]]:
    """Sementes válidas (sem erro) em todos os modos — a base pareada da comparação."""
    by_mode = {m: {r["seed"]: r for r in runs if r["mode"] == m and "error" not in r} for m in modes}
    seeds = sorted(set.intersection(*(set(v) for v in by_mode.values()))) if by_mode else []
    return seeds, by_mode


def _cell(values: list[float | None], n_total: int) -> str:
    vals = [v for v in values if v is not None]
    if not vals:
        return "—"
    text = f"{statistics.mean(vals):.2f}"
    if len(vals) > 1:
        text += f" ± {statistics.stdev(vals):.2f}"
    if len(vals) < n_total:
        text += f" (n={len(vals)})"
    return text


def _table(runs: list[dict[str, Any]], modes: list[str], metrics: list[tuple[str, str]],
           ref: str | None = None) -> list[str]:
    """Δ = cada modo LLM menos o modo de referência (por padrão, o penúltimo)."""
    present = {r["mode"] for r in runs}
    modes = [m for m in modes if m in present]
    if not modes:
        return ["(sem execuções)"]
    if ref not in modes:
        ref = modes[-2] if len(modes) > 1 else modes[0]
    compared = modes[modes.index(ref) + 1:]
    seeds, by_mode = _paired(runs, modes)
    lines = ["| métrica | " + " | ".join(modes + [f"Δ {m} − {ref}" for m in compared]) + " |",
             "|---|" + "---|" * (len(modes) + len(compared))]
    for key, label in metrics:
        cells = [_cell([by_mode[m][s].get(key) for s in seeds], len(seeds)) for m in modes]
        deltas = []
        for m in compared:
            diffs = [by_mode[m][s].get(key) - by_mode[ref][s].get(key) for s in seeds
                     if by_mode[m][s].get(key) is not None and by_mode[ref][s].get(key) is not None]
            deltas.append(_cell(diffs, len(seeds)))
        lines.append(f"| {label} | " + " | ".join(cells + deltas) + " |")
    lines.append(f"\nSementes pareadas: {seeds} (n = {len(seeds)}).")
    errors = [r for r in runs if "error" in r]
    lines.extend(f"- execução descartada ({r['mode']}, semente {r['seed']}): {r['error']}" for r in errors)
    return lines


def _flatten_violations(runs: list[dict[str, Any]], norms: list[str]) -> None:
    for r in runs:
        if "violations" in r:
            r["violations_total"] = sum(r["violations"].values())
            for n in norms:
                r[f"viol:{n}"] = r["violations"].get(n, 0)


def render_report(results: dict[str, Any]) -> str:
    lines = ["# Comparação: sem LLM × com LLM", ""]
    usage = results.get("usage")
    if usage:
        lines += [f"Modelo `{usage['model']}` (effort `{usage['effort']}`): {usage['calls']} chamadas, "
                  f"{usage['input_tokens']} tokens de entrada, {usage['output_tokens']} de saída, "
                  f"custo estimado US$ {usage['estimated_cost_usd']}.", ""]
    if "aborted" in results:
        lines += [f"**Execução interrompida:** {results['aborted']}", ""]
    cfg = results.get("config", {})
    lines.append("Valores: média ± desvio padrão sobre as sementes válidas em todos os modos; "
                 "Δ = média das diferenças pareadas por semente.")

    if results.get("marketplace"):
        runs = results["marketplace"]
        norms = ["MKT-NO-SELF", "MKT-NO-IMPERSONATION", "MKT-CONFIRM-NEEDS-ORDER"]
        _flatten_violations(runs, norms)
        lines += ["", "## Marketplace (arXiv:2307.06187, com normas)", ""]
        lines += _table(runs, ["offline", "llm"], [
            ("sales", "vendas"), ("mean_price", "preço médio"), ("unsold_sellers", "vendedores sem venda"),
            ("buyers_without_book", "compradores sem livro"), ("messages", "mensagens"),
            ("self_messages", "mensagens para si mesmo"), ("llm_failures", "falhas do LLM (usou a política offline)"), 
        ] + [(f"viol:{n}", f"violações {n}") for n in norms])
    if results.get("icu"):
        runs = results["icu"]
        _flatten_violations(runs, [])
        lines += ["", "## UTI (ANA-ML 2.0)", "",
                  f"Recomendador: heurístico × LLM. Validador LLM: {'sim' if cfg.get('llm_validator') else 'não'}; "
                  f"agente de decisão LLM: {'sim' if cfg.get('llm_decision') else 'não'}.", ""]
        lines += ["Modos: `static` (normas fixas); `adaptive-oracle` (recomendador heurístico + decisão com "
                  "rótulos perfeitos, só referência); `adaptive-heuristic` (recomendador heurístico + decisão "
                  "NEWS2); `adaptive-llm` (recomendador LLM + decisão NEWS2); `adaptive-llm-decision` "
                  "(recomendador heurístico + decisão LLM). Δ em relação a `adaptive-heuristic`.", ""]
        lines += _table(runs, ["static", "adaptive-oracle", "adaptive-heuristic", "adaptive-llm",
                               "adaptive-llm-decision"], [
            ("false_alarms", "alarmes falsos"), ("false_alarm_rate", "taxa de alarmes falsos"),
            ("sensitivity", "sensibilidade (alarme soou)"), ("specificity", "especificidade"),
            ("mean_latency", "latência do alarme (it.)"),
            ("recognized_sensitivity", "episódios reconhecidos pela decisão"),
            ("recognition_latency", "latência do reconhecimento (it.)"),
            ("verdict_accuracy", "acurácia dos vereditos"), ("verdict_sensitivity", "sensibilidade dos vereditos"),
            ("verdict_specificity", "especificidade dos vereditos"),
            ("news_accuracy", "ref.: acurácia NEWS2 nos mesmos alarmes"),
            ("bayes_accuracy", "ref.: acurácia do classificador ótimo"),
            ("wrong_labels_at_review", "rótulos errados usados nas revisões"),
            ("norm_changes_applied", "adaptações aplicadas"),
            ("norm_changes_rejected_validation", "rejeitadas pelo validador"),
            ("decision_defaults", "vereditos assumidos por padrão"), ("llm_failures", "falhas do LLM (usou a política offline)"), 
            ("violations_total", "violações de normas"),
        ], ref="adaptive-heuristic")
        audits = [r for r in runs if r.get("audit")]
        if audits:
            lines += ["", f"### Relatório do LLM-NormAuditor (semente {audits[0]['seed']})", "", audits[0]["audit"]]
    if results.get("project"):
        runs = results["project"]
        norms = ["PM-ASSIGN-BACKLOG", "PM-WIP-LIMIT"]
        _flatten_violations(runs, norms)
        lines += ["", "## Gestão de projetos (Tema 2)", ""]
        lines += _table(runs, ["offline", "llm"], [
            ("finished", "concluiu o projeto (fração)"),
            ("completion_censored", "iteração de conclusão (censurada no limite)"),
            ("tasks_done", "tarefas concluídas"), ("remaining_effort", "esforço restante"), ("llm_failures", "falhas do LLM (usou a política offline)"), 
        ] + [(f"viol:{n}", f"violações {n}") for n in norms])
    return "\n".join(lines) + "\n"
