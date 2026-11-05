"""Figuras do artigo (impressão, modo claro). Paleta validada com o validador da skill de dataviz:
azul #2a78d6, laranja #eb6834, água #1baf7a, amarelo #eda100 — contraste < 3:1 nos dois últimos,
por isso todas as barras levam rótulo de valor direto."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
GRAY, INK, INK2, GRID, SURFACE = "#9a9893", "#0b0b0b", "#52514e", "#e4e3df", "#ffffff"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8, "axes.edgecolor": INK2, "axes.labelcolor": INK,
    "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
    "axes.linewidth": 0.6, "xtick.major.width": 0.6, "ytick.major.width": 0.6, "figure.dpi": 300,
    "pdf.fonttype": 42,  # IEEE: fontes embutidas (TrueType) nas figuras vetoriais
})


def _save(fig, path: Path) -> None:
    """PNG para o rascunho em reportlab e PDF vetorial para o LaTeX."""
    fig.savefig(path, bbox_inches="tight")
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight")


def _grid(ax):
    ax.yaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def _rounded_bars(ax, x, heights, colors, width=0.62):
    bars = ax.bar(x, heights, width=width, color=colors, edgecolor=SURFACE, linewidth=1.5)
    return bars


def architecture(path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6.6, 3.3))
    ax.set_xlim(-1.5, 101.5)
    ax.set_ylim(0, 50)
    ax.axis("off")

    def box(x, y, w, h, title, body="", color=BLUE, fill="#eef4fc"):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2",
                                    linewidth=0.9, edgecolor=color, facecolor=fill))
        ax.text(x + w / 2, y + h - 2.2, title, ha="center", va="top", fontsize=7.5, fontweight="bold", color=INK)
        if body:
            ax.text(x + w / 2, y + h - 5.6, body, ha="center", va="top", fontsize=6.4, color=INK2, linespacing=1.3)

    def arrow(a, b, text="", color=INK2, rad=0.0, dy=1.2):
        ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=8, linewidth=0.8, color=color,
                                     connectionstyle=f"arc3,rad={rad}"))
        if text:
            ax.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + dy, text, ha="center", fontsize=6.2, color=INK2)

    # três colunas com vãos largos, para os rótulos das setas caberem entre as caixas
    box(0, 28, 27, 21, "Agent (MAPE-K)", "Monitor: sensors + messages\nAnalyze/Plan: LLM or\noffline policy\nExecute: actions\nKnowledge: local memory",
        BLUE, "#eef4fc")
    box(0, 1, 27, 19, "Environment", "synchronous rounds\npaired seeds\ncanonical message order\nexplicit conflict rules", GRAY, "#f4f3f1")
    box(37, 28, 25, 21, "Norm monitor", "prohibitions on actions\nobligations from facts\n(persistence, deadline)\nsanctions & rewards", ORANGE, "#fdf0ea")
    box(37, 1, 25, 19, "Norm knowledge base", "versioned norms\nper-context overrides\nchange history", ORANGE, "#fdf0ea")
    box(72, 28, 28, 21, "Norm adaptation", "evidence\n→ LLM-NormRecommender\n→ LLM-NormValidator\n(deterministic bounds)\n→ human supervisor", AQUA, "#e9f7f1")
    box(72, 1, 28, 19, "LLM-NormAuditor", "natural-language audit\nof norm effectiveness\nand adaptation history", AQUA, "#e9f7f1")

    def label(x, y, t):
        ax.text(x, y, t, ha="center", va="center", fontsize=6.2, color=INK2)

    arrow((13.5, 20.8), (13.5, 27.2)); label(20.5, 24, "perceive / act")
    arrow((27.8, 40), (36.2, 40)); label(32, 42.3, "actions")
    arrow((36.2, 35), (27.8, 35)); label(32, 32.7, "sanctions")
    arrow((49.5, 20.8), (49.5, 27.2)); label(56.5, 24, "norms in force")
    arrow((62.8, 40), (71.2, 40)); label(67, 42.3, "evidence")
    arrow((78, 27.2), (62.8, 15), rad=-0.1); ax.text(80, 22, "approved changes", ha="left", va="center", fontsize=6.2, color=INK2)
    arrow((62.8, 8), (71.2, 8)); label(67, 10.3, "history")
    _save(fig, path)
    plt.close(fig)


def icu_false_alarms(path: Path, data: dict) -> None:
    modes = data["icu_modes"]
    labels = ["Static\nnorms", "Oracle labels\n(reference)", "Heuristic\nrecommender\n+ NEWS2", "LLM\nrecommender\n+ NEWS2",
              "Heuristic\nrecommender\n+ LLM decision"]
    means = [data["icu"][m]["false_alarms"][0] for m in modes]
    colors = [GRAY, GRAY, GRAY, BLUE, BLUE]
    fig, ax = plt.subplots(figsize=(6.4, 2.7))
    x = range(len(modes))
    _rounded_bars(ax, x, means, colors)
    for i, m in enumerate(modes):
        pts = data["icu_seeds"][m]["false_alarms"]
        ax.scatter([i - 0.12, i, i + 0.12][:len(pts)], pts, s=10, color=INK, zorder=3, linewidths=0)
        ax.text(i, max(means[i], *pts) + 8, f"{means[i]:.1f}", ha="center", va="bottom", fontsize=7.5, color=INK)
    ax.set_xticks(list(x), labels, fontsize=7)
    ax.set_ylabel("False alarms per run (120 iterations)")
    ax.set_ylim(0, 275)
    _grid(ax)
    ax.text(4.45, 262, "dots: individual seeds   blue: LLM condition", ha="right", fontsize=6.5, color=INK2)
    _save(fig, path)
    plt.close(fig)


def decision_accuracy(path: Path, data: dict) -> None:
    rows = [("NEWS2 score\n(offline baseline)", data["icu"]["adaptive-heuristic"], "verdict_accuracy", GRAY),
            ("LLM decision\nagent", data["icu"]["adaptive-llm-decision"], "verdict_accuracy", BLUE),
            ("Bayes-optimal\n(knows generator)", data["icu"]["adaptive-llm-decision"], "bayes_accuracy", GRAY)]
    fig, ax = plt.subplots(figsize=(4.4, 2.5))
    vals = [r[1][r[2]][0] for r in rows]
    _rounded_bars(ax, range(3), vals, [r[3] for r in rows], width=0.55)
    for i, v in enumerate(vals):
        ax.text(i, v + 0.012, f"{v:.3f}", ha="center", va="bottom", fontsize=7.5, color=INK)
    ax.set_xticks(range(3), [r[0] for r in rows], fontsize=7)
    ax.set_ylim(0, 1.1)
    ax.set_ylabel("Verdict accuracy (alarm is real?)")
    _grid(ax)
    _save(fig, path)
    plt.close(fig)


def tradeoff(path: Path, data: dict) -> None:
    styles = {"static": (GRAY, "o", "Static norms"), "adaptive-oracle": (YELLOW, "D", "Oracle labels"),
              "adaptive-heuristic": (AQUA, "s", "Heuristic + NEWS2"), "adaptive-llm": (BLUE, "^", "LLM recommender"),
              "adaptive-llm-decision": (ORANGE, "v", "LLM decision")}
    fig, ax = plt.subplots(figsize=(5.2, 2.9))
    for m, (c, mk, lab) in styles.items():
        xs = data["icu_seeds"][m]["false_alarms"]
        ys = data["icu_seeds"][m]["mean_latency"]
        ax.scatter(xs, ys, s=34, color=c, marker=mk, edgecolors=SURFACE, linewidths=1.2, label=lab, zorder=3)
    ax.set_xlabel("False alarms per run")
    ax.set_ylabel("Alarm latency (iterations after onset)")
    _grid(ax)
    ax.xaxis.grid(True, color=GRID, linewidth=0.6)
    ax.legend(frameon=False, fontsize=6.8, loc="upper right", handletextpad=0.3)
    _save(fig, path)
    plt.close(fig)


def order_bias(path: Path) -> None:
    scen = ["Marketplace\n(600 runs)", "Project mgmt.\n(20 seeds)", "ICU\n(20 seeds)"]
    before, after = [97.0, 5.0, 0.0], [0.0, 0.0, 0.0]
    fig, ax = plt.subplots(figsize=(4.6, 2.4))
    w = 0.34
    xs = range(3)
    ax.bar([x - w / 2 - 0.01 for x in xs], before, width=w, color=ORANGE, edgecolor=SURFACE, linewidth=1.5,
           label="before (sequential rounds)")
    ax.bar([x + w / 2 + 0.01 for x in xs], after, width=w, color=BLUE, edgecolor=SURFACE, linewidth=1.5,
           label="after (synchronous rounds)")
    for x, b, a in zip(xs, before, after):
        ax.text(x - w / 2, b + 2, f"{b:.0f}%", ha="center", fontsize=7.5)
        ax.text(x + w / 2, a + 2, f"{a:.0f}%", ha="center", fontsize=7.5)
    ax.set_xticks(list(xs), scen, fontsize=7)
    ax.set_ylabel("Runs whose outcome changes\nwith agent order (%)")
    ax.set_ylim(0, 112)
    _grid(ax)
    ax.legend(frameon=False, fontsize=6.8, loc="upper right")
    _save(fig, path)
    plt.close(fig)


def deviation_vs_adaptation(path: Path, d2: dict) -> None:
    """Estudo 2: alarmes falsos e latência por forma de lidar com a fadiga (p = 0,3, sanção padrão)."""
    p = 0.3
    rows = [("Comply", d2["strategy"][("social", p, 1.0)], GRAY),
            ("Adapt", d2["adaptive"], GRAY),
            ("Selfish", d2["strategy"][("selfish", p, 1.0)], AQUA),
            ("Opport.", d2["strategy"][("opportunistic", p, 1.0)], AQUA),
            ("Rebel", d2["strategy"][("rebellious", p, 1.0)], ORANGE),
            ("LLM", d2["llm"][p], BLUE)]
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.6), gridspec_kw={"wspace": 0.32})
    for ax, key, label in ((axes[0], "false_alarms", "False alarms per run"),
                           (axes[1], "mean_latency", "Alarm latency (iterations)")):
        for i, (name, m, color) in enumerate(rows):
            val = m.get(key)
            if val is None:
                ax.bar(i, 0.0001, width=0.62, color="none")
                ax.text(i, 0.02 * ax.get_ylim()[1] if ax.get_ylim()[1] > 1 else 0.1, "pending", ha="center",
                        va="bottom", rotation=90, fontsize=6.5, color=INK2)
                continue
            ax.bar(i, val[0], width=0.62, color=color, edgecolor=SURFACE, linewidth=1.5)
            ax.text(i, val[0], f"{val[0]:.1f}" if key == "false_alarms" else f"{val[0]:.2f}", ha="center",
                    va="bottom", fontsize=6.5, color=INK)
        ax.set_xticks(range(len(rows)), [r[0] for r in rows], fontsize=6.8)
        ax.set_ylabel(label, fontsize=7)
        _grid(ax)
    axes[0].set_ylim(0, 250)
    axes[1].set_ylim(0, 6)
    _save(fig, path)
    plt.close(fig)


def deterrence(path: Path, d2: dict) -> None:
    """Estudo 2 (RQ6): parcela das obrigações reguladas suprimidas por probabilidade de detecção (sanção padrão)."""
    ps = d2["detections"]

    def share(m):
        return 100 * m["suppressions"][0] / m["deliberations"][0]

    # pressionado e oportunista coincidem com a sanção padrão: uma série só
    series = [("Rebellious", ORANGE, [d2["strategy"][("rebellious", p, 1.0)] for p in ps]),
              ("Selfish", AQUA, [d2["strategy"][("selfish", p, 1.0)] for p in ps]),
              ("Pressured = Opportunistic", YELLOW, [d2["strategy"][("pressured", p, 1.0)] for p in ps]),
              ("LLM", BLUE, [d2["llm"][p] for p in ps])]
    fig, ax = plt.subplots(figsize=(3.4, 2.5))
    for k, (name, color, ms) in enumerate(series):
        ys = [share(m) for m in ms]
        ax.plot(ps, ys, color=color, linewidth=2, marker="o", markersize=5, markeredgecolor=SURFACE,
                markeredgewidth=1, label=name, zorder=3 + k)
        if name == "LLM":
            for x, y in zip(ps, ys):
                ax.annotate(f"{y:.1f}%", (x, y), textcoords="offset points", xytext=(4, 5), fontsize=6.5, color=INK)
    ax.set_xticks(ps, [f"{p:g}" for p in ps])
    ax.set_xlabel("Detection probability p", fontsize=7)
    ax.set_ylabel("Regulated obligations suppressed (%)", fontsize=7)
    ax.set_ylim(-4, 108)
    ax.legend(fontsize=6.3, frameon=False, loc="center right", bbox_to_anchor=(1.0, 0.36))
    _grid(ax)
    _save(fig, path)
    plt.close(fig)


def make_all(out: Path, data: dict) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = {k: out / f"{k}.png" for k in ("architecture", "icu_false_alarms", "decision_accuracy", "tradeoff", "order_bias")}
    architecture(paths["architecture"])
    icu_false_alarms(paths["icu_false_alarms"], data)
    decision_accuracy(paths["decision_accuracy"], data)
    tradeoff(paths["tradeoff"], data)
    order_bias(paths["order_bias"])
    return paths
