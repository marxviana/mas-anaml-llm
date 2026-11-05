"""Extrai do experimento real (results/v3) todos os números citados no artigo."""

from __future__ import annotations

import itertools
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

RUN = ROOT / "results" / "v3"
PRICE_IN, PRICE_OUT = 4.0, 20.0  # claude-opus-5-5, US$/MTok


def mean_sd(values: list[float]) -> tuple[float, float]:
    vals = [v for v in values if v is not None]
    return statistics.mean(vals), (statistics.stdev(vals) if len(vals) > 1 else 0.0)


def sign_flip_p(diffs: list[float]) -> float:
    """Teste exato de permutação (inversão de sinais) para diferenças pareadas, bilateral."""
    obs = abs(statistics.mean(diffs))
    if obs == 0:
        return 1.0
    hits = sum(abs(statistics.mean([d * s for d, s in zip(diffs, signs)])) >= obs - 1e-12
               for signs in itertools.product((1, -1), repeat=len(diffs)))
    return hits / 2 ** len(diffs)


def by_mode(runs: list[dict]) -> dict[str, dict[int, dict]]:
    out: dict[str, dict[int, dict]] = defaultdict(dict)
    for r in runs:
        out[r["mode"]][r["seed"]] = r
    return out


def compare(groups: dict, a: str, b: str, key: str) -> dict:
    seeds = sorted(set(groups[a]) & set(groups[b]))
    va = [groups[a][s][key] for s in seeds]
    vb = [groups[b][s][key] for s in seeds]
    diffs = [y - x for x, y in zip(va, vb)]
    return {"a": mean_sd(va), "b": mean_sd(vb), "delta": mean_sd(diffs), "p": sign_flip_p(diffs),
            "per_seed_a": va, "per_seed_b": vb}


def load() -> dict:
    res = json.loads((RUN / "results.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (RUN / "transcripts.jsonl").read_text(encoding="utf-8").splitlines()]
    data: dict = {"usage": res["usage"], "config": res["config"]}

    # --- marketplace e projetos ------------------------------------------------
    mk = by_mode(res["marketplace"])
    data["market"] = {k: compare(mk, "offline", "llm", k) for k in
                      ("sales", "mean_price", "buyers_without_book", "unsold_sellers", "messages", "self_messages")}
    data["market"]["violations"] = {m: sum(sum(r["violations"].values()) for r in mk[m].values()) for m in mk}
    pj = by_mode(res["project"])
    data["project"] = {k: compare(pj, "offline", "llm", k) for k in ("completion_censored", "tasks_done", "finished")}
    data["project"]["backlog_viol"] = {m: sum(r["violations"].get("PM-ASSIGN-BACKLOG", 0) for r in pj[m].values())
                                       for m in pj}

    # --- UTI ---------------------------------------------------------------------
    icu = by_mode(res["icu"])
    modes = ["static", "adaptive-oracle", "adaptive-heuristic", "adaptive-llm", "adaptive-llm-decision"]
    keys = ["false_alarms", "false_alarm_rate", "sensitivity", "specificity", "mean_latency",
            "recognized_sensitivity", "recognition_latency", "verdict_accuracy", "verdict_sensitivity",
            "verdict_specificity", "news_accuracy", "bayes_accuracy", "wrong_labels_at_review",
            "norm_changes_applied", "llm_failures", "decision_defaults"]
    data["icu_modes"] = modes
    data["icu"] = {m: {k: mean_sd([icu[m][s][k] for s in sorted(icu[m])]) for k in keys} for m in modes}
    data["icu_seeds"] = {m: {k: [icu[m][s][k] for s in sorted(icu[m])] for k in keys} for m in modes}
    data["icu_cmp"] = {m: {k: compare(icu, "adaptive-heuristic", m, k) for k in keys}
                       for m in ("adaptive-llm", "adaptive-llm-decision")}
    data["icu_vs_static"] = {m: compare(icu, "static", m, "false_alarms") for m in modes[1:]}
    data["audit_excerpt"] = icu["adaptive-llm"][0].get("audit", "")

    # --- custo por componente -----------------------------------------------------
    cost: dict[str, dict[str, float]] = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0})
    for r in rows:
        tag = r["tag"]
        kind = ("ICU decision agent" if tag.endswith("/decision") else
                "ICU LLM-NormAuditor" if "Auditor" in r["system"] else
                "ICU LLM-NormRecommender" if tag.startswith("icu") else
                "Marketplace agents" if tag.startswith("marketplace") else "Project manager agent")
        c = cost[kind]
        c["calls"] += 1
        c["in"] += r["input_tokens"]
        c["out"] += r["output_tokens"]
    for c in cost.values():
        c["usd"] = (c["in"] * PRICE_IN + c["out"] * PRICE_OUT) / 1e6
    data["cost"] = dict(cost)

    # --- erros do agente de decisão LLM, por perfil -------------------------------
    from llm_mas.scenarios.icu import make_patients

    conf: Counter = Counter()
    for r in rows:
        if not r["tag"].endswith("/decision"):
            continue
        seed = int(r["tag"].split("seed")[1].split("/")[0])
        pts = {p.id: p for p in make_patients(12, 120, seed)}
        out = {a["patient"]: a["true_alarm"] for a in json.loads(r["output"])["assessments"]}
        for block in r["prompt"].split("ALERTA ")[1:]:
            pid = block.split()[0]
            t = int(re.search(r"leitura da iteração (\d+)", block).group(1))
            conf[(pts[pid].profile, pts[pid].in_episode(t), out[pid])] += 1
    data["decision_confusion"] = conf

    rec = [r for r in rows if r["tag"].endswith("/recommender") and "Recommender" in r["system"]]
    data["recommender_confirmation_mentions"] = (
        sum(1 for r in rec if re.search(r"confirm", r["output"], re.I)), len(rec))
    return data


def offline_icu(seeds=range(5)) -> dict:
    """Comparação offline com 5 sementes (normas estáticas × adaptação heurística)."""
    from llm_mas.scenarios.icu import compare_icu

    s = compare_icu(None, seeds=list(seeds))
    base = [r["baseline"] for r in s["runs"]]
    adap = [r["adaptive"] for r in s["runs"]]
    return {"summary": s,
            "fa_static": mean_sd([b["false_alarms"] for b in base]), "fa_adaptive": mean_sd([a["false_alarms"] for a in adap]),
            "lat_static": mean_sd([b["mean_latency"] for b in base]), "lat_adaptive": mean_sd([a["mean_latency"] for a in adap]),
            "lat_up": sum(a["mean_latency"] > b["mean_latency"] for a, b in zip(adap, base)), "n": len(base)}


if __name__ == "__main__":
    d = load()
    print(json.dumps({k: v for k, v in d.items() if k not in ("decision_confusion", "audit_excerpt", "icu_seeds", "icu_cmp", "market", "project")}, indent=1, default=str)[:2500])
    for m in d["icu_modes"]:
        print(m, {k: round(d["icu"][m][k][0], 3) for k in ("false_alarms", "mean_latency", "verdict_accuracy", "norm_changes_applied")})
    for m, c in d["icu_cmp"].items():
        print(m, "Δfa", c["false_alarms"]["delta"], "p", c["false_alarms"]["p"])
    print("market", {k: (v["a"], v["b"], v["p"]) for k, v in d["market"].items() if isinstance(v, dict) and "a" in v})
    print("project", {k: (v["a"], v["b"], v["p"]) for k, v in d["project"].items() if isinstance(v, dict) and "a" in v})
    print(sorted(d["decision_confusion"].items()))
    o = offline_icu()
    print("offline", {k: v for k, v in o.items() if k != "summary"}, o["summary"].get("paired_t"))
