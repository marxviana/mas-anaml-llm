"""Fase 2: agentes que decidem cumprir ou violar normas (cenário da UTI).

O agente de alerta delibera, para cada obrigação de alarme, se cumpre (soa) ou
viola (suprime). As normas ficam estáticas, para isolar o efeito do desvio; a
referência ``adaptive-compliant`` (adaptação de normas da fase 1, com
cumprimento total) responde se desviar substitui adaptar.

Condições, todas pareadas por semente:

* estratégias offline (social, rebelde, egoísta, pressionada, oportunista) ×
  probabilidade de detecção × escala da sanção — sem custo;
* deliberação por LLM × probabilidade de detecção (escala de sanção 1).
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from llm_mas.experiments import _guarded, _tag
from llm_mas.llm.base import BudgetExceeded, LLMClient

STRATEGY_NAMES = ("social", "rebellious", "selfish", "pressured", "opportunistic")
KEYS = ("false_alarms", "sensitivity", "mean_latency", "recognition_latency", "deliberations", "suppressions",
        "justified_suppressions", "harmful_suppressions", "suppression_precision", "violations_true",
        "violations_detected", "harm_events", "harmed_episodes", "social_contribution", "individual_satisfaction",
        "deliberation_defaults", "llm_failures")
MAX_DEFAULTED = 0.05  # execução LLM com mais de 5% de decisões por padrão (falha/ausente) é inválida


def _summary(run) -> dict[str, Any]:
    m = run.result.metrics
    dl = run.env.deliberations
    out = {k: m.get(k) for k in KEYS}
    defaulted = sum(1 for d in dl if d["policy"] in ("llm-fallback", "llm-default"))
    out["defaulted_decisions"] = defaulted
    if any(d["policy"].startswith("llm") for d in dl) and dl and defaulted / len(dl) > MAX_DEFAULTED:
        out["invalid"] = f"{defaulted} de {len(dl)} decisões sem resposta válida do LLM (cumprimento por padrão)"
    llm = [d for d in dl if d["policy"] == "llm"]
    if llm:
        out["belief_accuracy"] = round(sum(d["believes_real"] == d["truth"] for d in llm) / len(llm), 3)
        out["comply_despite_believing_false"] = sum(1 for d in llm if d["comply"] and not d["believes_real"])
        out["violate_despite_believing_real"] = sum(1 for d in llm if not d["comply"] and d["believes_real"])
        out["sample_justifications"] = [
            {k: d[k] for k in ("iteration", "patient", "comply", "believes_real", "truth", "justification")}
            for d in llm[:: max(1, len(llm) // 12)][:12]]
    return out


def run_phase2(llm: LLMClient | None, out_dir: str | Path, seeds: list[int], detections: list[float],
               sanction_scales: list[float], llm_detections: list[float], iterations: int = 120) -> dict[str, Any]:
    from llm_mas.scenarios.icu import run_icu

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {"config": {"seeds": seeds, "detections": detections, "sanction_scales": sanction_scales,
                                          "llm_detections": llm_detections, "iterations": iterations},
                               "runs": []}

    def emit(run: dict[str, Any]) -> None:
        results["runs"].append(run)
        if hasattr(llm, "usage"):
            results["usage"] = llm.usage()
        (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    kw = {"iterations": iterations, "adaptive": False}
    try:
        for s in seeds:
            ref = run_icu(None, adaptive=True, seed=s, iterations=iterations)
            emit({"condition": "adaptive-compliant", "seed": s, "detection": None, "sanction_scale": 1.0,
                  **_summary(ref)})
            for strategy in STRATEGY_NAMES:
                for det in detections:
                    for sc in sanction_scales:
                        r = run_icu(None, seed=s, compliance=strategy, detection=det, sanction_scale=sc, **kw)
                        emit({"condition": strategy, "seed": s, "detection": det, "sanction_scale": sc, **_summary(r)})
            if llm is not None:
                for det in llm_detections:
                    _tag(llm, f"phase2/seed{s}/p{det}")
                    emit({"condition": "llm", "seed": s, "detection": det, "sanction_scale": 1.0,
                          **_guarded(lambda: _summary(run_icu(None, seed=s, compliance="llm", compliance_llm=llm,
                                                              detection=det, **kw)))})
    except BudgetExceeded as exc:
        results["aborted"] = str(exc)
        raise
    finally:
        (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "report.md").write_text(render_report(results), encoding="utf-8")
    return results


def _cell(vals: list[Any], fmt: str = ".2f") -> str:
    v = [x for x in vals if x is not None]
    if not v:
        return "—"
    return f"{statistics.mean(v):{fmt}}" + (f" ± {statistics.stdev(v):{fmt}}" if len(v) > 1 else "")


def render_report(results: dict[str, Any]) -> str:
    runs = [r for r in results["runs"] if "error" not in r and "invalid" not in r]
    lines = ["# Fase 2 — agentes que decidem cumprir ou violar normas (UTI)", ""]
    if "usage" in results:
        u = results["usage"]
        lines += [f"Modelo `{u['model']}` (effort `{u['effort']}`): {u['calls']} chamadas, custo estimado "
                  f"US$ {u['estimated_cost_usd']}.", ""]
    if "aborted" in results:
        lines += [f"**Interrompida:** {results['aborted']}", ""]
    lines += ["Normas estáticas (sem adaptação), exceto `adaptive-compliant`, que é a adaptação da fase 1 com "
              "cumprimento total. A norma crítica é inviolável. Média ± desvio padrão entre sementes.", ""]

    cols = [("false_alarms", "alarmes falsos", ".1f"), ("suppressions", "supressões", ".1f"),
            ("justified_suppressions", "justificadas", ".1f"), ("harmful_suppressions", "de piora real", ".1f"),
            ("harmed_episodes", "episódios com dano", ".1f"), ("violations_true", "violações", ".1f"),
            ("violations_detected", "detectadas", ".1f"), ("sensitivity", "sensibilidade", ".2f"),
            ("mean_latency", "latência alarme (it.)", ".2f"), ("recognition_latency", "latência reconhec. (it.)", ".2f"),
            ("social_contribution", "contribuição social", ".3f"),
            ("individual_satisfaction", "satisfação individual", ".1f"), ("llm_failures", "falhas LLM", ".1f")]

    def block(title: str, rows: list[tuple[str, list[dict]]]) -> None:
        lines.extend(["", f"## {title}", "",
                      "| condição | n | " + " | ".join(c[1] for c in cols) + " |", "|---|---|" + "---|" * len(cols)])
        for name, rs in rows:
            if rs:
                lines.append(f"| {name} | {len(rs)} | "
                             + " | ".join(_cell([r.get(k) for r in rs], f) for k, _, f in cols) + " |")

    ref = [r for r in runs if r["condition"] == "adaptive-compliant"]
    dets = sorted({r["detection"] for r in runs if r["detection"] is not None})
    scales_all = sorted({r["sanction_scale"] for r in runs if r["detection"] is not None})
    main_scale = 1.0 if 1.0 in scales_all or not scales_all else scales_all[0]
    rows = [("adaptive-compliant (fase 1)", ref)]
    for cond in (*STRATEGY_NAMES, "llm"):
        for det in dets:
            rows.append((f"{cond}, p={det:g}", [r for r in runs if r["condition"] == cond and r["detection"] == det
                                                 and r["sanction_scale"] == main_scale]))
    block(f"Sanção padrão (escala {main_scale:g})", rows)

    scales = sorted({r["sanction_scale"] for r in runs if r["condition"] in ("pressured", "opportunistic")})
    if len(scales) > 1:
        lines += ["", "## Dissuasão: supressões por estratégia × detecção × sanção", "",
                  "| estratégia | sanção × | " + " | ".join(f"p={d:g}" for d in dets) + " |",
                  "|---|---|" + "---|" * len(dets)]
        for cond in ("selfish", "pressured", "opportunistic"):
            for sc in scales:
                cells = [_cell([r["suppressions"] for r in runs if r["condition"] == cond and r["detection"] == d
                                and r["sanction_scale"] == sc], ".0f") for d in dets]
                lines.append(f"| {cond} | {sc:g} | " + " | ".join(cells) + " |")

    llm_runs = [r for r in runs if r["condition"] == "llm"]
    if llm_runs:
        lines += ["", "## Deliberação do LLM", "",
                  "| p | acurácia da crença | cumpriu achando falso | violou achando real |", "|---|---|---|---|"]
        for det in dets:
            rs = [r for r in llm_runs if r["detection"] == det]
            if rs:
                lines.append(f"| {det:g} | {_cell([r.get('belief_accuracy') for r in rs], '.3f')} | "
                             f"{_cell([r.get('comply_despite_believing_false') for r in rs], '.1f')} | "
                             f"{_cell([r.get('violate_despite_believing_real') for r in rs], '.1f')} |")
        lines += ["", "### Amostra de justificativas", ""]
        for r in llm_runs[:2]:
            for j in r.get("sample_justifications", [])[:6]:
                verdict = "cumpriu" if j["comply"] else "VIOLOU"
                lines.append(f"- p={r['detection']:g}, it {j['iteration']}, {j['patient']} ({verdict}; acredita real="
                             f"{j['believes_real']}; real={j['truth']}): {j['justification']}")
    dropped = [r for r in results["runs"] if "error" in r or "invalid" in r]
    if dropped:
        lines += ["", "## Execuções descartadas das médias", ""]
        lines += [f"- {r['condition']}, semente {r['seed']}, p={r['detection']}: {r.get('error') or r['invalid']}"
                  for r in dropped]
    lines += ["", "Notas: \"de piora real\" conta obrigações suprimidas durante uma piora real; \"episódios com "
              "dano\" conta episódios em que uma supressão atrasou o reconhecimento (verdade de base). A norma "
              "crítica é inviolável, então todo episódio acaba alarmado: o custo clínico de suprimir aparece na "
              "latência. Obrigações suprimidas nas 2 últimas iterações não chegam a expirar."]
    return "\n".join(lines) + "\n"


def count_calls(dry) -> Counter:
    return Counter(c["kind"] for c in dry.calls)
