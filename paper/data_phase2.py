"""Números do Estudo 2 (fase 2: cumprir ou violar normas).

Estratégias offline: results/phase2-offline (sem custo, já executado).
LLM: results/phase2-llm, se existir; senão os valores ficam ``None`` e o
artigo mostra XPTO. Rodar a fase 2 com LLM nessa pasta e regenerar o PDF
preenche tudo automaticamente:

    .venv/bin/llm-mas deliberation --llm claude --effort low --out results/phase2-llm
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OFFLINE = ROOT / "results" / "phase2-offline" / "results.json"
LLM = ROOT / "results" / "phase2-llm" / "results.json"
STRATEGIES = ("social", "rebellious", "selfish", "pressured", "opportunistic")
METRICS = ("deliberations", "false_alarms", "suppressions", "justified_suppressions", "harmful_suppressions", "harmed_episodes",
           "violations_true", "violations_detected", "mean_latency", "recognition_latency", "social_contribution",
           "individual_satisfaction", "belief_accuracy", "comply_despite_believing_false",
           "violate_despite_believing_real")


def _mean(vals):
    v = [x for x in vals if x is not None]
    return (statistics.mean(v), statistics.stdev(v) if len(v) > 1 else 0.0) if v else None


def _group(runs, cond, det, scale):
    return [r for r in runs if r["condition"] == cond and r.get("detection") == det
            and r.get("sanction_scale") == scale and "error" not in r and "invalid" not in r]


def load() -> dict:
    off = json.loads(OFFLINE.read_text(encoding="utf-8"))
    runs = off["runs"]
    dets = off["config"]["detections"]
    scales = off["config"]["sanction_scales"]
    d: dict = {"seeds": off["config"]["seeds"], "detections": dets, "scales": scales}
    ref = [r for r in runs if r["condition"] == "adaptive-compliant"]
    d["adaptive"] = {m: _mean([r.get(m) for r in ref]) for m in METRICS}
    d["strategy"] = {(s, p, sc): {m: _mean([r.get(m) for r in _group(runs, s, p, sc)]) for m in METRICS}
                     for s in STRATEGIES for p in dets for sc in scales}

    d["llm_available"] = False
    d["llm"] = {p: {m: None for m in METRICS} for p in dets}
    d["llm_n"] = {p: 0 for p in dets}
    d["llm_usage"] = None
    d["llm_samples"] = []
    # a rodada completa parou no teto de custo antes de (semente 2, p = 1.0), executada depois em outra pasta
    llm_runs, calls, tin, tout, tin_used, tout_used = {}, 0, 0, 0, 0, 0
    for folder in sorted(LLM.parent.parent.glob("phase2-llm*")):
        if not (folder / "results.json").exists():
            continue
        res = json.loads((folder / "results.json").read_text(encoding="utf-8"))
        valid = {}
        for r in res["runs"]:
            if r["condition"] == "llm" and "error" not in r and "invalid" not in r:
                valid[f"phase2/seed{r['seed']}/p{r['detection']}"] = r
                llm_runs.setdefault((r["seed"], r["detection"]), r)
        for line in (folder / "transcripts.jsonl").read_text(encoding="utf-8").splitlines():
            t = json.loads(line)
            calls, tin, tout = calls + 1, tin + t["input_tokens"], tout + t["output_tokens"]
            if t["tag"] in valid:
                tin_used, tout_used = tin_used + t["input_tokens"], tout_used + t["output_tokens"]
    if llm_runs:
        runs = list(llm_runs.values())
        d["llm_available"] = True
        price = lambda i, o: (i * 4 + o * 20) / 1e6  # Opus 5.5: US$ 4/20 por milhão de tokens
        d["llm_usage"] = {"calls": calls, "input_tokens": tin, "output_tokens": tout, "cost": price(tin, tout),
                          "cost_discarded": price(tin - tin_used, tout - tout_used)}
        for p in dets:
            g = [r for r in runs if r["detection"] == p]
            d["llm_n"][p] = len(g)
            d["llm"][p] = {m: _mean([r.get(m) for r in g]) for m in METRICS}
        d["llm_samples"] = [j for r in runs for j in r.get("sample_justifications", [])]
    return d


if __name__ == "__main__":
    d = load()
    print("adaptive", {k: v for k, v in d["adaptive"].items() if v})
    for s in STRATEGIES:
        for p in d["detections"]:
            x = d["strategy"][(s, p, 1.0)]
            print(f"{s:13} p={p}: FA={x['false_alarms'][0]:.1f} sup={x['suppressions'][0]:.1f} "
                  f"harmEp={x['harmed_episodes'][0]:.1f} lat={x['mean_latency'][0]:.2f} "
                  f"sat={x['individual_satisfaction'][0]:.1f} social={x['social_contribution']}")
    print("llm available:", d["llm_available"])
