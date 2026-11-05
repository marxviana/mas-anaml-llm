"""Análise das justificativas da deliberação por LLM (Estudo 2, RQ7).

Lê as transcrições de results/phase2-llm*/ e cruza cada decisão (cumprir ou não,
crença declarada) com os temas citados na justificativa e com o histórico
normativo que o prompt mostrava. Usa só execuções completas, que são as que
entram nas tabelas; chamadas de uma execução interrompida pelo teto de custo são
descartadas.
"""

from __future__ import annotations

import json
import sys
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# temas por palavras-chave (pt e en); uma justificativa pode citar vários
THEMES = {
    "detection": r"detec|auditori|audit|probabilidad|probabilit|fiscaliz",
    "sanction": r"sanç|sancion|sanction|punish|puni",
    "harm": r"\bdano|\bharm|penalidade 20|penalty of 20|20-point",
    "safety": r"seguran|safety|\bsafe",
    "norm": r"\bnorma|obriga|\bnorm\b|\bnorms\b|obligation|cumpro|comply",
    "fatigue": r"fadiga|fatigue|satisfa",
    "uncertainty": r"incert|dúvida|duvida|descartar|uncertain|cannot rule out|can't rule out|doubt",
    "artifact": r"artefato|artifact|pletism|pleth",
    "trend": r"tendênc|tendenc|trend|estável|estavel|stable",
}
EN = re.compile(r"\b(the|is|and|with|this|not|patient's)\b", re.I)
SANCTIONS = re.compile(r"violações detectadas e sancionadas: (\d+)")


def _runs(results_path: Path) -> set[str]:
    res = json.loads(results_path.read_text(encoding="utf-8"))
    return {f"phase2/seed{r['seed']}/p{r['detection']}" for r in res["runs"]
            if r["condition"] == "llm" and "error" not in r and "invalid" not in r}


def decisions() -> list[dict]:
    out = []
    for folder in sorted(ROOT.glob("results/phase2-llm*")):
        if not (folder / "results.json").exists() or not (folder / "transcripts.jsonl").exists():
            continue
        valid = _runs(folder / "results.json")
        for line in (folder / "transcripts.jsonl").read_text(encoding="utf-8").splitlines():
            t = json.loads(line)
            if t["tag"] not in valid:
                continue
            p = float(t["tag"].rsplit("/p", 1)[1])
            m = SANCTIONS.search(t["prompt"])
            for d in json.loads(t["output"])["decisions"]:
                j = d["justification"]
                out.append({"tag": t["tag"], "p": p, "comply": d["comply"], "believes_real": d["believes_real"],
                            "sanctioned_before": int(m.group(1)) if m else 0,
                            "english": len(EN.findall(j)) >= 3,
                            **{k: bool(re.search(rx, j, re.I)) for k, rx in THEMES.items()}})
    return out


def kind(d: dict) -> str:
    if not d["comply"]:
        return "violated"
    return "complied, believed real" if d["believes_real"] else "complied, believed false"


def summary() -> dict:
    ds = decisions()
    s: dict = {"n": len(ds), "runs": len({d["tag"] for d in ds})}
    groups = defaultdict(list)
    for d in ds:
        groups[(kind(d), d["p"])].append(d)
        groups[(kind(d), None)].append(d)
    s["themes"] = {key: {"n": len(g), **{k: sum(d[k] for d in g) / len(g) for k in THEMES}}
                   for key, g in groups.items()}
    s["english"] = sum(d["english"] for d in ds) / len(ds) if ds else None
    # aprendizado com a fiscalização: taxa de violação antes e depois da primeira sanção detectada (p = 0.3)
    low = [d for d in ds if d["p"] == 0.3 and not d["believes_real"]]
    before = [d for d in low if d["sanctioned_before"] == 0]
    after = [d for d in low if d["sanctioned_before"] > 0]
    s["learning"] = {"before_n": len(before), "after_n": len(after),
                     "before": sum(not d["comply"] for d in before) / len(before) if before else None,
                     "after": sum(not d["comply"] for d in after) / len(after) if after else None}
    s["kinds"] = Counter(kind(d) for d in ds)
    return s


if __name__ == "__main__":
    s = summary()
    print("decisões", s["n"], "execuções", s["runs"], "em inglês", s["english"])
    print("tipos", dict(s["kinds"]))
    print("aprendizado (p=0.3, crê falso)", s["learning"])
    for key in sorted(s["themes"], key=lambda k: (k[0], -1 if k[1] is None else k[1])):
        t = s["themes"][key]
        print(key, t["n"], {k: round(v, 2) for k, v in t.items() if k != "n"})


def replay() -> dict:
    """Reexecuta cada execução válida respondendo com as saídas gravadas do LLM (sem custo).

    Recupera a verdade de base de cada decisão e confere que as métricas
    reproduzidas são idênticas às registradas."""
    sys.path.insert(0, str(ROOT / "src"))
    from llm_mas.llm import FunctionLLM
    from llm_mas.scenarios.icu import run_icu

    out = {}
    for folder in sorted(ROOT.glob("results/phase2-llm*")):
        if not (folder / "results.json").exists():
            continue
        res = json.loads((folder / "results.json").read_text(encoding="utf-8"))
        answers = defaultdict(dict)
        for line in (folder / "transcripts.jsonl").read_text(encoding="utf-8").splitlines():
            t = json.loads(line)
            answers[t["tag"]][t["prompt"]] = json.loads(t["output"])
        for r in res["runs"]:
            if r["condition"] != "llm" or "error" in r or "invalid" in r:
                continue
            book = answers[f"phase2/seed{r['seed']}/p{r['detection']}"]
            run = run_icu(adaptive=False, seed=r["seed"], iterations=res["config"]["iterations"], compliance="llm",
                          compliance_llm=FunctionLLM(lambda system, prompt, schema: book[prompt]),
                          detection=r["detection"])
            m = run.result.metrics
            same = all(m.get(k) == r.get(k) for k in ("false_alarms", "suppressions", "harmed_episodes",
                                                      "violations_detected", "individual_satisfaction"))
            out[(r["seed"], r["detection"])] = {"identical": same, "deliberations": run.env.deliberations}
    return out


def belief_confusion(rep: dict) -> dict:
    """Crença declarada × verdade, por p (somadas as sementes)."""
    conf = defaultdict(Counter)
    for (seed, p), r in rep.items():
        for d in r["deliberations"]:
            conf[p][(d["believes_real"], d["truth"])] += 1
    return conf


def mcnemar(a: int, b: int) -> float:
    """Teste exato de McNemar (binomial bilateral) para pares discordantes a e b."""
    from math import comb

    n, k = a + b, min(a, b)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def belief_shift(rep: dict, a: float = 0.3, b: float = 1.0) -> dict:
    """Mesma obrigação (semente, iteração, paciente, normas) decidida em p = a e p = b: a crença mudou?"""
    by = defaultdict(dict)
    for (seed, p), r in rep.items():
        for d in r["deliberations"]:
            by[(seed, d["iteration"], d["patient"], tuple(d["norms"]))][p] = d["believes_real"]
    pairs = [v for v in by.values() if a in v and b in v]
    to_false = sum(1 for v in pairs if v[a] and not v[b])
    to_real = sum(1 for v in pairs if not v[a] and v[b])
    return {"n": len(pairs), "to_false": to_false, "to_real": to_real, "p": mcnemar(to_false, to_real)}
