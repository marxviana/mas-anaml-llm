"""Gera paper/paper.pdf a partir do experimento real (results/v3).

    .venv/bin/python paper/build_paper.py

Todos os números do texto vêm de ``data.py``; nada é digitado à mão, exceto a
medição do viés de ordem antes da correção (o código antigo não existe mais) e
os achados da revisão de engenharia (Tabela 6), registrados durante o desenvolvimento.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

import data as D  # noqa: E402
import data_phase2 as D2  # noqa: E402
import figures  # noqa: E402

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
pdfmetrics.registerFont(TTFont("Serif", str(FONT_DIR / "DejaVuSerif.ttf")))
pdfmetrics.registerFont(TTFont("Serif-Bold", str(FONT_DIR / "DejaVuSerif-Bold.ttf")))
pdfmetrics.registerFont(TTFont("Sans", str(FONT_DIR / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("Sans-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFontFamily("Serif", normal="Serif", bold="Serif-Bold", italic="Serif", boldItalic="Serif-Bold")
pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans", boldItalic="Sans-Bold")

INK = colors.HexColor("#0b0b0b")
INK2 = colors.HexColor("#52514e")
RULE = colors.HexColor("#c9c7c1")
HEAD_BG = colors.HexColor("#eef4fc")

S = {
    "title": ParagraphStyle("title", fontName="Serif-Bold", fontSize=16.5, leading=21, alignment=TA_CENTER,
                            spaceAfter=8, textColor=INK),
    "authors": ParagraphStyle("authors", fontName="Serif", fontSize=9.5, leading=13, alignment=TA_CENTER,
                              textColor=INK2, spaceAfter=14),
    "abs": ParagraphStyle("abs", fontName="Serif", fontSize=8.8, leading=12.2, alignment=TA_JUSTIFY,
                          leftIndent=0.8 * cm, rightIndent=0.8 * cm, spaceAfter=6),
    "h1": ParagraphStyle("h1", fontName="Sans-Bold", fontSize=11, leading=14, spaceBefore=12, spaceAfter=5, textColor=INK),
    "h2": ParagraphStyle("h2", fontName="Sans-Bold", fontSize=9.6, leading=12.5, spaceBefore=8, spaceAfter=3,
                         textColor=INK),
    "p": ParagraphStyle("p", fontName="Serif", fontSize=9.3, leading=13.1, alignment=TA_JUSTIFY, spaceAfter=5.5,
                        textColor=INK),
    "cap": ParagraphStyle("cap", fontName="Sans", fontSize=7.8, leading=10.3, alignment=TA_JUSTIFY, textColor=INK2,
                          spaceBefore=3, spaceAfter=9),
    "cell": ParagraphStyle("cell", fontName="Sans", fontSize=7.3, leading=9.2, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Sans-Bold", fontSize=7.3, leading=9.2, textColor=INK),
    "ref": ParagraphStyle("ref", fontName="Serif", fontSize=8.1, leading=10.6, leftIndent=0.6 * cm,
                          firstLineIndent=-0.6 * cm, spaceAfter=2.5, alignment=TA_JUSTIFY),
}

TEXT_WIDTH = A4[0] - 4.2 * cm


def P(text: str, style: str = "p") -> Paragraph:
    return Paragraph(text, S[style])


def bullets(items: list[str]) -> ListFlowable:
    return ListFlowable([ListItem(P(t), leftIndent=12, value="•") for t in items], bulletType="bullet",
                        start="•", leftIndent=12, bulletFontName="Serif", bulletFontSize=8)


def table(rows: list[list[str]], widths: list[float], caption: str, bold_first_col: bool = False) -> KeepTogether:
    cells = [[Paragraph(str(c), S["cellb" if (r == 0 or (bold_first_col and i == 0)) else "cell"])
              for i, c in enumerate(row)] for r, row in enumerate(rows)]
    t = Table(cells, colWidths=[w * TEXT_WIDTH for w in widths], repeatRows=1)
    t.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, INK), ("LINEBELOW", (0, 0), (-1, 0), 0.5, INK),
        ("LINEBELOW", (0, -1), (-1, -1), 0.8, INK), ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2), ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        *[("LINEBELOW", (0, r), (-1, r), 0.25, RULE) for r in range(1, len(rows) - 1)],
    ]))
    return KeepTogether([P(caption, "cap"), t, Spacer(1, 8)])


def figure(path: Path, width_frac: float, caption: str) -> KeepTogether:
    from reportlab.lib.utils import ImageReader

    w, h = ImageReader(str(path)).getSize()
    width = width_frac * TEXT_WIDTH
    return KeepTogether([Image(str(path), width=width, height=width * h / w), P(caption, "cap")])


def ms(pair: tuple[float, float], fmt: str = ".2f") -> str:
    return f"{pair[0]:{fmt}} ± {pair[1]:{fmt}}"


def X(text: str = "XPTO") -> str:
    """Marca um dado que depende da rodada do Estudo 2 com LLM (ainda não executada)."""
    return f"<font color='#c62828'><b>{text}</b></font>"


def v(pair, fmt: str = ".1f") -> str:
    return X() if pair is None else f"{pair[0]:{fmt}}"


def vms(pair, fmt: str = ".1f") -> str:
    return X() if pair is None else ms(pair, fmt)


def pct(a: float, b: float) -> str:
    return f"{100 * (a - b) / a:.0f}%"


def make_story() -> list:
    """Monta o conteúdo com os helpers P/bullets/table/figure/X deste módulo;
    build_tex.py os substitui para gerar LaTeX a partir do mesmo texto."""
    d = D.load()
    off = D.offline_icu()
    figs = figures.make_all(HERE / "figures", d)
    ic, seeds = d["icu"], d["icu_seeds"]
    fa = {m: ic[m]["false_alarms"][0] for m in d["icu_modes"]}
    rec = d["icu_cmp"]["adaptive-llm"]
    dec = d["icu_cmp"]["adaptive-llm-decision"]
    mk, pj = d["market"], d["project"]
    usage = d["usage"]
    conf = d["decision_confusion"]
    n_dec = sum(conf.values())
    acc_dec = sum(n for (_, truth, verdict), n in conf.items() if truth == verdict) / n_dec
    conf_mentions, n_rec_calls = d["recommender_confirmation_mentions"]
    fp = sum(n for (p, t, v_), n in conf.items() if not t and v_)
    fn = sum(n for (p, t, v_), n in conf.items() if t and not v_)
    d2 = D2.load()
    s2, a2, L = d2["strategy"], d2["adaptive"], d2["llm"]
    soc, sel, opp, reb = (s2[(k, 0.3, 1.0)] for k in ("social", "selfish", "opportunistic", "rebellious"))
    pres = s2[("pressured", 0.3, 1.0)]
    fig_dev = HERE / "figures" / "deviation.png"
    figures.deviation_vs_adaptation(fig_dev, d2)
    fig_det = HERE / "figures" / "deterrence.png"
    figures.deterrence(fig_det, d2)

    # Estudo 2, LLM: análise das decisões reproduzidas a partir das transcrições (sem custo)
    import justifications as J

    assert d2["llm_available"], "rode a fase 2 com LLM antes de gerar o artigo"
    js, rep = J.summary(), J.replay()
    assert all(r["identical"] for r in rep.values()), "a reexecução não reproduziu as métricas registradas"
    conf2 = J.belief_confusion(rep)
    shift = J.belief_shift(rep)
    u2 = d2["llm_usage"]
    L3 = L[0.3]
    sup_rate = {pv: 100 * L[pv]["suppressions"][0] / L[pv]["deliberations"][0] for pv in d2["detections"]}
    bel = {pv: {"sens": c[(True, True)] / (c[(True, True)] + c[(False, True)]),
                "spec": c[(False, False)] / (c[(False, False)] + c[(True, False)]),
                "false_as_real": c[(True, False)], "n_false": c[(False, False)] + c[(True, False)]}
           for pv, c in conf2.items()}
    news_spec = sel["suppressions"][0] / soc["false_alarms"][0]  # NEWS2: falsos que o egoísta julgou falsos
    believed_false_03 = (conf2[0.3][(False, False)] + conf2[0.3][(False, True)]) / 3
    viol_share_03 = L3["suppressions"][0] / believed_false_03
    th = js["themes"]
    learn = js["learning"]
    story: list = []

    # ------------------------------------------------------------------ título
    story += [
        P("Do Large Language Models Improve Adaptive Normative Agents? "
          "Norm Adaptation and Norm Compliance in Paired Simulations", "title"),
        P("Marx Viana — Pontifical Catholic University of Rio de Janeiro (PUC-Rio), Brazil<br/>"
          "<font color='#9a9893'>[co-authors and affiliations to be confirmed]</font>", "authors"),
        # IEEE Access: um parágrafo, 150–250 palavras, sem referências nem tabelas
        P("<b>Abstract.</b> Large language models are increasingly proposed as reasoning components of normative "
          "multi-agent systems, yet their benefit over deterministic alternatives is rarely measured. We report two "
          "exploratory, controlled studies on an open platform in which every language-model component has a "
          "deterministic counterpart and all conditions are paired by seed and independent of agent order. The "
          "first study uses language models to adapt norms in a book marketplace, an intensive care alarm system "
          "and software project management. Language-model agents completed more trades, and adaptive norms "
          f"reduced false alarms by {pct(fa['static'], fa['adaptive-heuristic'])}, but a language-model norm "
          "recommender was worse than a deterministic one, and a language-model decision agent only matched a "
          "clinical early-warning score. The second study lets the alerting agent decide whether to comply with "
          "each alarm obligation under imperfect enforcement. A selfish strategy guided by the clinical score "
          "removed more false alarms than norm adaptation without harming patients, whereas a rebellious strategy "
          "delayed the recognition of deterioration; a regimented critical norm bounded the harm. The "
          f"language-model agent suppressed {sup_rate[0.3]:.0f}% of regulated alarms when detection was unlikely "
          "and almost none when it was certain, never suppressed a real deterioration and never harmed a patient. "
          "Its stated beliefs were cautious and always coherent with its decisions, but for the same alarms they "
          "shifted with the probability of detection, so its justifications partly rationalize its choices. We "
          "also report seventeen engineering threats to validity and their controls. With three seeds per "
          "condition, all findings are exploratory.", "abs"),
        P("<b>Keywords:</b> enforcement, large language models, MAPE-K, multi-agent systems, norm compliance, "
          "normative systems, self-adaptive systems, simulation, threats to validity.", "abs"),
    ]

    # ------------------------------------------------------------- 1 introdução
    story += [
        P("1 Introduction", "h1"),
        P("Multi-agent systems (MAS) operating in regulated domains are typically governed by <i>norms</i>—"
          "obligations, prohibitions and permissions with associated sanctions and rewards [6]. Our earlier work "
          "proposed the ANA metamodel and the ANA-ML modeling language to represent adaptive normative agents "
          "explicitly [2, 3], and the JSAN framework to implement them [4]. Norms in such systems are usually "
          "static: thresholds, deadlines and scopes are fixed at design time, which is problematic when the "
          "environment changes or when one norm must serve heterogeneous contexts."),
        P("Large Language Models offer a tempting remedy. LLM-based agents can encapsulate the analysis, "
          "planning and knowledge stages of the MAPE-K loop [1, 11], and LLM components can interpret natural-"
          "language norms, recommend refinements, validate candidate norms and audit their effects. ANA-ML 2.0 "
          "proposes exactly these constructs—LLM-NormProcessor, LLM-NormRecommender, LLM-NormValidator and "
          "LLM-NormAuditor—and motivates them with an ICU patient-monitoring case in which adaptive norms "
          "should reduce false alarms and response times [5]."),
        P("Such expectations are hard to verify. LLM agents are stochastic and costly to run; simulations of "
          "interacting agents contain subtle sources of bias; and a fair comparison requires a non-LLM baseline "
          "that receives exactly the same information. In practice, it is easy to obtain impressive numbers from a "
          "setup that silently favors one condition. This paper reports an exploratory, controlled study designed "
          "to avoid these pitfalls. Our main findings are:"),
        bullets([
            f"In open negotiation, LLM agents completed twice as many trades as heuristic agents "
            f"({mk['sales']['b'][0]:.0f} vs. {mk['sales']['a'][0]:.0f} per run) at higher prices, and did not "
            "exhibit the self-messaging behavior reported in earlier LLM-MAS experiments [1].",
            f"Adaptive norms reduced ICU false alarms by {pct(fa['static'], fa['adaptive-heuristic'])}, but the "
            f"gain came from adaptation itself: the LLM-NormRecommender produced {rec['false_alarms']['delta'][0]:+.0f} "
            "false alarms per run relative to a deterministic recommender, because it adapted less under "
            "uncertain labels.",
            "An LLM decision agent was as accurate as a NEWS2-based clinical score, not better, and adaptation "
            "increased alarm latency rather than reducing it.",
            "Nine engineering threats to validity—order bias, off-by-one measurement, ground-truth leakage, "
            "ambiguous command semantics and others—would each have distorted the comparison had they gone "
            "unnoticed; two were first revealed by the LLM-NormAuditor itself.",
        ]),
        P("Study 1 treats the LLM as a component <i>of</i> the norms—recommending, validating and auditing them. "
          "The ANA metamodel, however, also allows agents to decide <i>not</i> to comply with a norm when its "
          "rewards and punishments do not justify it [2]. Study 2 therefore asks a complementary question: rather "
          "than adapting a norm to reduce alarm fatigue, can an autonomous agent <i>deviate</i> from it, and what "
          "does deviation cost? We compare five classical compliance strategies [6] with an LLM deliberative agent "
          "under different enforcement levels. Its main findings are:"),
        bullets([
            f"Well-informed deviation outperformed norm adaptation offline: a selfish strategy suppressing only "
            f"alarms judged false by NEWS2 left {sel['false_alarms'][0]:.1f} false alarms per run (adaptation: "
            f"{a2['false_alarms'][0]:.1f}) with no harmed episode and unchanged latency.",
            f"Uninformed deviation was costly: a rebellious strategy harmed {reb['harmed_episodes'][0]:.1f} episodes "
            f"per run and more than doubled alarm latency; the regimented critical norm was the safety net.",
            "Enforcement separated the strategies as theory predicts: opportunistic agents responded to detection "
            "probability, pressured agents to the expected sanction.",
            f"The LLM deliberative agent was safe but cautious: it suppressed {sup_rate[0.3]:.1f}% of regulated "
            f"alarms at p = 0.3 and {sup_rate[1.0]:.1f}% at p = 1.0, all of them false, and harmed no patient; it "
            f"thus removed far fewer false alarms ({L3['false_alarms'][0]:.1f} left) than a selfish agent guided by "
            "a clinical score.",
            "Its stated beliefs were always coherent with its decisions, yet for the very same alarms they moved "
            f"with the detection probability ({shift['to_false']} beliefs changed from \"real\" to \"false\" and "
            f"{shift['to_real']} the other way between p = 0.3 and p = 1.0; exact McNemar p = {shift['p']:.4f}): "
            "LLM justifications partly rationalize the decision rather than report an independent judgment.",
        ]),
        P("Our contributions are: (i) <i>llm-mas</i>, an open platform in which every LLM component has a "
          "deterministic counterpart, enabling paired comparisons; (ii) an evidence model for ICU alarms with "
          "imperfect, noisy observations, a clinical-score baseline and a Bayes-optimal ceiling; (iii) an empirical "
          "comparison across three scenarios; (iv) an operationalization of the ANA normative process with "
          "classical compliance strategies, imperfect enforcement and a regimented safety norm, compared with an "
          "LLM deliberative agent; and (v) a catalog of engineering threats to validity for LLM-based MAS "
          "simulations, with the controls we adopted. Section 2 presents the background, Section 3 the design of "
          "both studies, Sections 4 and 5 their results, Section 6 the implications, Section 7 the threats to "
          "validity, and Section 8 concludes."),
    ]

    # --------------------------------------------------------------- 2 background
    story += [
        P("2 Background", "h1"),
        P("2.1 Adaptive normative agents", "h2"),
        P("Following López y López et al. [6] and the ANA metamodel [2], a norm is characterized by its "
          "<i>addressee</i> (agents or roles responsible for it), <i>deontic concept</i> (obligation, prohibition "
          "or permission), <i>activation</i> and <i>expiration</i> conditions, the <i>state</i> or action it "
          "regulates, and the <i>rewards</i> and <i>punishments</i> associated with fulfilling or violating it. "
          "ANA extends the TAO and FAML metamodels [8, 9] with adaptation entities—Collect (sensors), Analyze "
          "(strategies), Decision (plans) and Effector (actuators)—and with a normative process in which agents "
          "become aware of norms, deliberate about them, decide whether to comply, and update their goals. "
          "ANA-ML represents these concepts as a UML-based language [2, 3]; JSAN provides an implementation "
          "framework [4]."),
        P("Fig. 7 shows the ANA-BDI architecture that operationalizes this process [2]. A <i>normative component</i> "
          "holds the norms beside the agent's beliefs, desires, intentions and plans; an <i>adaptive component</i> "
          "runs a Collect–Analyze–Decision–Effector loop. Collect monitors and adopts norms; Analyze conditions "
          "them, verifies whether they are being fulfilled, estimates their <i>normative contribution</i> to the "
          "agent's goals and detects and solves conflicts; Decision weighs the importance of the available options "
          "and selects a plan; and the Effector carries out the normative decision—which may be to fulfill the "
          "norm or to violate it. The separation between Analyze, which forms judgments, and Decision, which "
          "chooses, matters for Study 2: it is where an LLM can be placed, and it is what our analysis of LLM "
          "beliefs and decisions probes."),
        figure(HERE / "figures" / "ana_bdi.png", 0.62,
               "<b>Figure 7.</b> ANA-BDI architecture of an adaptive normative agent (reproduced from [2]). Study 2 "
               "maps the alarm obligations, the deliberation and the alarm decision onto its Collect, Analyze, "
               "Decision and Effector stages."),
        P("2.2 LLM-based self-adaptive agents", "h2"),
        P("Nascimento, Alencar and Cowan [1] proposed agents whose MAPE-K loop [10, 11] delegates Analyze, Plan and "
          "Knowledge to an LLM: the Monitor stage turns sensors and received messages into a prompt, and the "
          "Execute stage parses the LLM output into actions. In a book marketplace with sellers and buyers, they "
          "observed both effective negotiation and undesired behaviors, such as an agent sending messages to "
          "itself while impersonating a customer, and they identified the lack of memory across iterations as a "
          "limitation."),
        P("2.3 LLM components for norm adaptation", "h2"),
        P("ANA-ML 2.0 [5] introduces LLM-based constructs for continuous norm adaptation: an "
          "<i>LLM-NormRecommender</i> proposes context-aware refinements; an <i>LLM-NormValidator</i> checks "
          "consistency and conflicts; an <i>LLM-NormAuditor</i> reports on norm effectiveness in natural language; "
          "and a human-in-the-loop supervisor approves changes. Its motivating case is ICU monitoring, where static "
          "alarm thresholds produce alarm fatigue. Clinical practice offers a strong non-LLM reference for alarm "
          "triage: the National Early Warning Score 2 (NEWS2) [7], which aggregates points for vital signs and "
          "level of consciousness, with a dedicated SpO<sub>2</sub> scale for patients with hypercapnic "
          "respiratory failure."),
    ]

    story += [
        P("2.4 Norm compliance and enforcement", "h2"),
        P("Autonomous agents may violate norms. López y López, Luck and d'Inverno [6] characterize agents by how "
          "they decide to comply—among them <i>social</i> agents that always comply, <i>rebellious</i> agents that "
          "never do, <i>pressured</i> agents that comply when punishments would hinder their goals, and "
          "<i>opportunistic</i> agents that weigh whether violations will be detected; in the ANA metamodel, norms "
          "carry rewards and punishments precisely so that the agent can decide whether compliance is worthwhile "
          "[2]. JSAN evaluated such strategies through the agents' <i>social contribution</i> and <i>individual "
          "satisfaction</i> [4]. Two enforcement mechanisms are commonly distinguished: <i>regimentation</i>, in "
          "which the architecture makes violations impossible, and <i>regulation</i>, in which violations are "
          "possible but detected—often imperfectly—and sanctioned."),
    ]

    # ------------------------------------------------------------ 3 study design
    cost = d["cost"]
    story += [
        P("3 Study Design", "h1"),
        P("We conducted an exploratory study to quantify what LLM components add to adaptive normative agents "
          "when compared with deterministic counterparts that receive the same information.", "p"),
        P("3.1 Goal and research questions", "h2"),
        bullets([
            "<b>RQ1:</b> How do LLM-driven agents compare with heuristic agents in open negotiation and in "
            "coordination under dynamic contexts, and do they violate norms?",
            "<b>RQ2:</b> Does an LLM-NormRecommender reduce ICU false alarms relative to a deterministic "
            "recommender, without loss of safety?",
            "<b>RQ3:</b> How accurately does an LLM decision agent classify alarms under imperfect evidence, "
            "relative to a clinical score and to the Bayes-optimal ceiling?",
            "<b>RQ4:</b> Which engineering threats to validity arise when building LLM-based MAS simulations, "
            "and how can they be controlled?",
            "<b>RQ5</b> (Study 2)<b>:</b> Can autonomous deviation from alarm norms substitute norm adaptation in "
            "reducing false alarms, and at what safety cost?",
            "<b>RQ6</b> (Study 2)<b>:</b> How do detection probability and sanction size shape compliance by "
            "classical strategies and by an LLM deliberative agent?",
            "<b>RQ7</b> (Study 2)<b>:</b> When the LLM violates a norm, is the violation justified, and are its "
            "stated beliefs and justifications coherent with its decisions?",
        ]),
        P("RQ1–RQ3 are answered by Study 1 (Section 4), RQ5–RQ7 by Study 2 (Section 5), and RQ4 draws on both."),
        P("3.2 Platform", "h2"),
        P("<i>llm-mas</i> is a Python platform (Fig. 1). Each agent runs a MAPE-K loop whose Analyze/Plan stage "
          "is either an LLM call or an offline policy; a local memory of perceived and executed events is "
          "summarized in the prompt, addressing the limitation reported in [1]. The environment runs synchronous "
          "rounds: all agents decide on the same state, actions are applied together, and messages sent at "
          "iteration <i>t</i> are delivered at <i>t</i>+1. A norm monitor evaluates prohibitions on actions and "
          "opens obligations from environment facts, with persistence (consecutive activations required), "
          "deadlines, sanctions and rewards; sanctions are written to the violating agent's memory. A norm "
          "adaptation engine implements the ANA-ML 2.0 pipeline: evidence → recommender → validator → supervisor "
          "→ versioned norm knowledge base. Safety bounds in the validator are always deterministic: an LLM can "
          "reject a proposal but never approve one that violates a bound. Non-adaptable norms (e.g., a critical "
          "ICU alarm for SpO<sub>2</sub> &lt; 85%) never change."),
        figure(figs["architecture"], 0.92,
               "<b>Figure 1.</b> Architecture of llm-mas. Every LLM component (agent reasoning, recommender, "
               "validator review, auditor) has a deterministic counterpart, so conditions can be compared "
               "pairwise on identical environments."),
        P("3.3 Scenarios", "h2"),
        table([
            ["Scenario", "Agents", "Norms", "Role of the LLM", "Main metrics"],
            ["Book marketplace (from [1])", "3 sellers, 2 buyers; 3 iterations",
             "no self-messages; no impersonation; Confirm_sale only after a matching Buy_Book",
             "all five agents negotiate in free text", "sales, price, unsold sellers, norm violations"],
            ["ICU alarm management (from [5])", "2 monitors, 1 alerting agent, 1 decision agent; 12 patients; "
             "120 iterations", "4 adaptable alarm obligations (SpO<sub>2</sub>, HR, SBP, RR) + 1 critical, "
             "non-adaptable", "norm recommender (RQ2) or decision agent (RQ3)",
             "false alarms, sensitivity, latency, verdict accuracy"],
            ["Project management (dynamic contexts)", "1 manager, 4–5 developers; 60 iterations",
             "WIP limit (prohibition); assign unowned tasks within 2 iterations (obligation)",
             "manager allocates tasks under 5 context events", "completion iteration, tasks done, violations"],
        ], [0.17, 0.2, 0.25, 0.18, 0.2], "<b>Table 1.</b> Scenarios, agents, norms and the role played by the LLM."),
        P("In the ICU scenario, patients belong to four physiological profiles (no chronic disease, COPD, chronic "
          "tachycardia, chronic hypotension); half of them develop a 10-iteration deterioration episode, and 5% of "
          "SpO<sub>2</sub> readings are motion artifacts. The alerting agent fulfills alarm obligations; the "
          "decision agent judges whether each alarm reflects real deterioration; those verdicts become the "
          "evidence on which norms are adapted per patient (e.g., a lower SpO<sub>2</sub> threshold and 2-reading "
          "persistence for a COPD patient). The project scenario injects requirement changes, a developer leaving "
          "and another joining, a bug spike and a productivity drop."),
        P("3.4 Imperfect evidence, baselines and ceiling", "h2"),
        P("A naive ICU simulation can leak the ground truth to the decision agent—for instance, through a bedside "
          "report that states \"signs of deterioration\" exactly when the alarm is real. We replaced it with an "
          "observation model: bedside findings (dyspnea, sweating, altered consciousness, slow capillary refill, "
          "complaint) occur with partial sensitivity and specificity that grow with the deterioration stage, "
          "chronic conditions produce baseline findings (e.g., 50% dyspnea in COPD), and a poor plethysmography "
          "signal appears in 70% of artifacts and 10% of clean readings. The decision agent receives the "
          "triggering reading, the last six readings, the chronic diagnosis and the findings—never the hidden "
          "state. True outcomes are confirmed only 30 iterations after an alarm; until then, adaptation relies on "
          "the decision agent's verdicts, errors included."),
        P("The offline decision policy is a modified NEWS2 score [7]: NEWS2 points on the triggering vital signs "
          "(scale 2 for COPD), plus one point per bedside finding, minus two points when an artifact is suspected; "
          "an alarm is deemed real when the score is ≥ 5, the NEWS2 threshold for urgent review. The threshold was "
          "fixed before any run and does not use the generator's parameters. As a ceiling we compute, on the same "
          "alarms, a Bayes-optimal classifier that knows the generative model, marginalizing over deterioration "
          "stage and artifact occurrence; it is a reference, never a policy."),
        P("3.5 Experimental conditions and controls", "h2"),
        table([
            ["Condition", "Norm recommender", "Decision agent", "Purpose"],
            ["static", "—", "NEWS2", "traditional, non-adaptive baseline"],
            ["adaptive-oracle", "deterministic", "oracle (true labels)", "upper reference for adaptation"],
            ["adaptive-heuristic", "deterministic", "NEWS2", "non-LLM adaptive baseline (Δ reference)"],
            ["adaptive-llm", "<b>LLM</b>", "NEWS2", "RQ2: only the recommender changes"],
            ["adaptive-llm-decision", "deterministic", "<b>LLM</b>", "RQ3: only the decision agent changes"],
        ], [0.22, 0.2, 0.2, 0.38], "<b>Table 2.</b> ICU conditions. Each LLM condition differs from "
                                   "adaptive-heuristic in exactly one component."),
        P("All conditions are paired by seed: the same seed yields the same patients, readings, bedside findings "
          "(drawn from a seed derived from patient and iteration) and project scenario. The platform is "
          "order-invariant by construction and by test: results do not depend on the order in which agents are "
          "registered (Section 4.4). Commands such as <tt>Buy_Book: 30</tt> or <tt>assign T3</tt> take effect "
          "only when they are the entire message; the environment notifies agents of commands without effect. "
          "Prompts state the same protocol rules that the heuristic policies follow by construction."),
        P("3.6 Model, cost and analysis", "h2"),
        P(f"We used Claude Opus 5.5 (<tt>claude-opus-5-5</tt>) with effort <i>low</i>, structured JSON outputs for "
          f"the recommender and decision agent, and server-side refusal fallback. Before spending, a dry run "
          f"executed the whole experiment with a recording client and estimated US$ 4.76 from token counts "
          f"calibrated on earlier runs and one paid probe; the actual cost was US$ {usage['estimated_cost_usd']:.2f} "
          f"for {usage['calls']} calls ({usage['input_tokens']:,} input and {usage['output_tokens']:,} output "
          f"tokens), with no API failures (Table 7). We ran three seeds (0–2) per condition. We report means ± "
          f"standard deviations and paired differences; for significance we use the exact two-sided sign-flip "
          f"permutation test on paired differences. With n = 3, its smallest attainable p-value is 0.25, so no "
          f"comparison can reach conventional significance: this study is exploratory by design."),
    ]

    strat_rows = [["Strategy", "Decision rule (operationalization)"],
                  ["social", "always complies"],
                  ["rebellious", "violates whenever the architecture allows (any non-regimented obligation)"],
                  ["selfish", "violates when violating favors its own goals (it judges the alarm false), "
                              "ignoring sanctions"],
                  ["pressured", "violates only if the gain of violating exceeds detection × sanction + reward"],
                  ["opportunistic", "violates when it favors its goals and detection is unlikely (p &lt; 0.5)"],
                  ["LLM", "decides in natural language from the same information, returning belief, decision "
                          "and justification"]]
    story += [
        P("3.7 Study 2: deciding whether to comply", "h2"),
        P("Study 2 reuses the ICU scenario with <i>static</i> norms and makes the alerting agent deliberative, "
          "following the ANA normative process [2]: <i>awareness</i> of each newly opened alarm obligation, "
          "<i>deliberation</i>, a <i>compliance</i> decision—raise the alarm (comply) or suppress it (violate)—and "
          "<i>impact</i> on its beliefs when sanctions or outcomes arrive. Each obligation is decided once. The "
          "critical norm (SpO<sub>2</sub> &lt; 85% or equivalent) is <i>regimented</i>: the architecture always "
          "raises it, so every episode is eventually alarmed and the clinical cost of suppression appears as "
          "delay. The other four alarm norms are <i>regulated</i>: a violation is detected with probability p and "
          "then sanctioned; undetected violations are recorded for analysis only."),
        P("The agent's goals carry ANA <i>Motivation</i> values—patient safety 10 and avoiding alarm fatigue 6—and "
          "suppressing an alarm it judges false has <i>Satisfaction</i> 3. Each fulfilled obligation is rewarded "
          "with 1 point and each detected violation sanctioned with 5 points times a sanction scale. The outcome "
          "of every suppressed alarm is confirmed 30 iterations after the reading; if a real deterioration was "
          "suppressed before any true alarm of that episode, a harm penalty of 20 is charged, once per episode. "
          "These values were fixed before any run. Offline strategies judge an alarm real when the modified NEWS2 "
          "score of Study 1 is ≥ 5 (Table 8)."),
        table(strat_rows, [0.18, 0.82], "<b>Table 8.</b> Compliance strategies, operationalized from [6] on the "
                                         "same information given to the LLM."),
        P("The LLM deliberative agent receives, for each pending obligation, the same evidence as the decision "
          "agent of Study 1 (triggering reading, six-reading trend, chronic diagnosis, bedside findings), the "
          "reward, sanction and detection probability, its goals, and a permanent normative record (obligations "
          "fulfilled, sanctions, confirmed outcomes of past suppressions, harms). It returns, per patient, whether "
          "it believes the deterioration is real, whether it complies, and why. A failed or missing answer "
          "defaults to compliance and is counted; runs with more than 5% defaulted decisions are excluded. As in "
          "Study 1, all prompts are written in Portuguese and the model answers through a JSON schema whose patient "
          "field is restricted to the pending obligations."),
        P("The agent instantiates the ANA-BDI loop (Fig. 7): the norm monitor <i>collects</i> each new alarm "
          "obligation; a deliberation strategy <i>analyzes</i> it; the <i>decision</i> is to comply or violate; "
          "and the <i>effector</i> raises or suppresses the alarm. In JSAN, deliberation is a framework hot spot, "
          "<tt>NormDeliberation</tt>, plugged into the frozen <tt>Analyze</tt> behavior through the "
          "<tt>IReasoningStrategy</tt> interface (Fig. 8). Our five classical strategies and the LLM are "
          "interchangeable implementations of this one hot spot: they receive the same case—norms, reward, "
          "sanction, detection probability and the evidence—and return a decision. The comparison therefore "
          "isolates the reasoning strategy, which is exactly the variation point that ANA-ML 2.0 proposes to fill "
          "with an LLM. Its operations map onto our deliberation case as follows: <i>conditionNorms</i> selects "
          "the regulated (non-regimented) obligations; <i>fulfillingNorms</i> weighs the reward of compliance; "
          "<i>normativeContribution</i> weighs the expected sanction and the risk of harm against the goal of "
          "avoiding alarm fatigue; and <i>detectingSolvingConflicts</i> resolves the conflict between the agent's "
          "two goals."),
        figure(HERE / "figures" / "jsan_norm_deliberation.png", 0.95,
               "<b>Figure 8.</b> Norm deliberation as a hot spot of the JSAN framework [4]. The classical "
               "strategies and the LLM of Study 2 are alternative implementations of this hot spot."),
        table([["Condition", "Norms", "Compliance", "Detection p", "Sanction scale"],
               ["adaptive-compliant", "adaptive (Study 1)", "always", "—", "—"],
               ["strategies", "static", "5 strategies (Table 8)", "0.3, 0.7, 1.0", "0.2, 1, 3"],
               ["LLM", "static", "LLM deliberation", "0.3, 0.7, 1.0", "1"]],
              [0.2, 0.18, 0.24, 0.18, 0.2], "<b>Table 9.</b> Study 2 conditions (3 paired seeds each)."),
        P("<b>Metrics.</b> Besides false alarms and latency, we report suppressions, split into <i>justified</i> "
          "(the alarm was false) and <i>of real deterioration</i>; <i>harmed episodes</i>, in which a suppression "
          "delayed recognition; violations, all and detected; <i>social contribution</i>, the share of obligations "
          "on real deterioration that were complied with; and the agent's <i>individual satisfaction</i>—action "
          "satisfaction plus rewards minus detected sanctions and harm penalties [4]. For the LLM we also report "
          "belief accuracy and decision–belief coherence."),
        P("<b>Verification before spending.</b> Because the LLM runs are costly, the environment was verified "
          "first: (i) all 15 offline Study 1 runs were reproduced exactly after the Study 2 changes; (ii) 13 "
          "equivalence tests replace the LLM with an emulator that reads only the prompt text and applies an "
          "offline rule—the simulations are identical to those of the corresponding offline policy for all five "
          "strategies, two detection levels and a different sanction scale, and for the Study 1 decision agent and "
          "recommender—showing that prompts carry the information the policies use and that answers are parsed and "
          "applied correctly; (iii) ten invariant tests cover determinism, pairing, order invariance and metric "
          "accounting; (iv) a second independent code review found four defects, fixed before any paid run (Table "
          "6, rows 10–14); and (v) the output schema was validated against the API at no cost. A dry run estimated "
          "930 calls (about US$ 15.35) for the LLM conditions."),
        P(f"<b>Execution.</b> The nine LLM runs (three seeds × three detection levels) made 930 valid calls, as "
          f"estimated, but the dry run underestimated the length of the justifications ({u2['output_tokens']:,} "
          "output tokens in total against 338,400 estimated). The budget cap therefore stopped the planned "
          "execution during its last run; that run was discarded, and the missing combination (seed 2, p = 1.0) "
          "was executed separately with the same code. Because the offline strategies are deterministic, we "
          "checked that all of their runs were identical across the two executions and the offline study. "
          f"The total cost was US$ {u2['cost']:.2f} for {u2['calls']} calls ({u2['input_tokens']:,} input and "
          f"{u2['output_tokens']:,} output tokens), of which US$ {u2['cost_discarded']:.2f} belonged to the "
          "discarded run. No call failed and no decision was defaulted."),
        P("<b>Replay.</b> Every LLM call is stored with its prompt and answer. For the analysis of RQ7 we re-ran "
          "each LLM run offline, answering each prompt with the recorded answer. All nine replays reproduced the "
          "recorded metrics exactly, which confirms that the runs are reproducible from their transcripts and gives "
          "us, at no cost, the ground truth behind every decision."),
    ]

    # ------------------------------------------------------------------ 4 results
    m, p_ = mk, pj
    story += [
        P("4 Results", "h1"),
        P("4.1 RQ1 – Negotiation and coordination", "h2"),
        table([
            ["Metric", "Heuristic", "LLM", "Δ (LLM − heur.)", "p"],
            ["Sales per run", ms(m["sales"]["a"], ".1f"), ms(m["sales"]["b"], ".1f"), ms(m["sales"]["delta"], ".1f"),
             f"{m['sales']['p']:.2f}"],
            ["Mean sale price (US$)", ms(m["mean_price"]["a"], ".1f"), ms(m["mean_price"]["b"], ".1f"),
             ms(m["mean_price"]["delta"], ".1f"), f"{m['mean_price']['p']:.2f}"],
            ["Buyers without a book", ms(m["buyers_without_book"]["a"], ".1f"), ms(m["buyers_without_book"]["b"], ".1f"),
             ms(m["buyers_without_book"]["delta"], ".1f"), f"{m['buyers_without_book']['p']:.2f}"],
            ["Messages", ms(m["messages"]["a"], ".1f"), ms(m["messages"]["b"], ".1f"), ms(m["messages"]["delta"], ".1f"),
             f"{m['messages']['p']:.2f}"],
            ["Self-messages", ms(m["self_messages"]["a"], ".0f"), ms(m["self_messages"]["b"], ".0f"), "0", "—"],
            ["Norm violations (total, 3 runs)", str(m["violations"]["offline"]), str(m["violations"]["llm"]), "", ""],
            ["<b>Project:</b> completion iteration", ms(p_["completion_censored"]["a"], ".1f"),
             ms(p_["completion_censored"]["b"], ".1f"), ms(p_["completion_censored"]["delta"], ".1f"),
             f"{p_['completion_censored']['p']:.2f}"],
            ["<b>Project:</b> tasks completed", ms(p_["tasks_done"]["a"], ".0f"), ms(p_["tasks_done"]["b"], ".0f"),
             "0", "—"],
            ["<b>Project:</b> backlog-norm violations", str(p_["backlog_viol"]["offline"]), str(p_["backlog_viol"]["llm"]),
             "", ""],
        ], [0.34, 0.16, 0.16, 0.2, 0.14], "<b>Table 3.</b> Marketplace and project results (3 paired seeds; "
                                         "mean ± s.d.; p from exact sign-flip test, minimum 0.25)."),
        P(f"LLM agents completed two sales in every run (vs. one), leaving no buyer without a book, and sold at "
          f"higher prices (US$ {m['mean_price']['b'][0]:.1f} vs. {m['mean_price']['a'][0]:.1f}). Initial asking "
          "prices varied widely (US$ 8–50): some sellers anchored high and conceded, others undercut aggressively; "
          "buyers broadcast offers to several sellers; the "
          "explicit conflict rule (earliest matching order wins) resolved simultaneous confirmations. No agent sent "
          "messages to itself. The single violation was genuine rather than a simulator artifact: a seller sent two "
          "confirmations at different prices to the same buyer, one of which no longer matched the buyer's order. "
          "The heuristic baseline is weak in this scenario—both heuristic buyers always target the cheapest seller—"
          "so the size of the LLM advantage should not be generalized."),
        P(f"In project management, both managers completed all tasks without backlog-norm violations; the LLM "
          f"manager finished {p_['completion_censored']['delta'][0]:.1f} iterations later on average (p = "
          f"{p_['completion_censored']['p']:.2f}). The only violations were WIP-limit breaches by a developer "
          "configured as undisciplined, identical in both conditions, after which the developer adapted to the "
          "sanction. <b>Answer to RQ1:</b> LLM agents negotiated more effectively and respected the protocol "
          "norms; in task allocation, they matched but did not surpass a load-balancing heuristic."),
        P("4.2 RQ2 – LLM-based norm recommendation", "h2"),
        figure(figs["icu_false_alarms"], 0.92,
               "<b>Figure 2.</b> ICU false alarms per run by condition (bars: mean of 3 seeds; dots: seeds). Blue "
               "bars change exactly one component to an LLM relative to the heuristic condition."),
        table([
            ["Metric"] + ["Static", "Oracle", "Heuristic", "LLM rec.", "LLM dec."],
            *[[label] + [ms(ic[mm][key], fmt) for mm in d["icu_modes"]] for label, key, fmt in [
                ("False alarms", "false_alarms", ".1f"), ("Sensitivity (alarm raised)", "sensitivity", ".2f"),
                ("Specificity", "specificity", ".3f"), ("Alarm latency (it.)", "mean_latency", ".2f"),
                ("Episodes recognized", "recognized_sensitivity", ".2f"),
                ("Recognition latency (it.)", "recognition_latency", ".2f"),
                ("Norm changes applied", "norm_changes_applied", ".1f"),
                ("Wrong labels used in reviews", "wrong_labels_at_review", ".1f"),
                ("Verdict accuracy", "verdict_accuracy", ".3f"), ("Verdict sensitivity", "verdict_sensitivity", ".2f"),
                ("Verdict specificity", "verdict_specificity", ".3f"),
                ("Bayes-optimal accuracy (same alarms)", "bayes_accuracy", ".3f")]],
        ], [0.3, 0.14, 0.14, 0.14, 0.14, 0.14],
            "<b>Table 4.</b> ICU results by condition (3 paired seeds, mean ± s.d.). LLM rec. = adaptive-llm; "
            "LLM dec. = adaptive-llm-decision. No norm violations and no LLM failures occurred in any condition."),
        P(f"Adaptation was effective: relative to static norms, the deterministic recommender reduced false alarms "
          f"by {pct(fa['static'], fa['adaptive-heuristic'])} ({fa['static']:.1f} → {fa['adaptive-heuristic']:.1f}) "
          f"and perfect labels would reduce them by {pct(fa['static'], fa['adaptive-oracle'])}, with sensitivity "
          f"preserved at 1.0 in every condition and the critical norm never altered. A five-seed offline replication "
          f"confirmed the effect ({off['fa_static'][0]:.1f} → {off['fa_adaptive'][0]:.1f}; paired t = "
          f"{off['summary']['paired_t']:.2f}, df = 4). The LLM recommender, however, was worse than the "
          f"deterministic one: {fa['adaptive-llm']:.1f} vs. {fa['adaptive-heuristic']:.1f} false alarms "
          f"(Δ = {ms(rec['false_alarms']['delta'], '.1f')}, worse in all three seeds, p = "
          f"{rec['false_alarms']['p']:.2f}). It applied fewer changes ({ic['adaptive-llm']['norm_changes_applied'][0]:.1f} "
          f"vs. {ic['adaptive-heuristic']['norm_changes_applied'][0]:.1f}), and {conf_mentions} of its "
          f"{n_rec_calls} responses mentioned that verdicts were not yet confirmed by outcomes. In one seed, the "
          "LLM-NormAuditor's report likewise noted that adaptations relied largely on unconfirmed verdicts and "
          "recommended suspending further adaptation until confirmation—a cautious stance that, here, left "
          "avoidable false alarms in place."),
        figure(figs["tradeoff"], 0.72,
               "<b>Figure 3.</b> False alarms versus alarm latency per seed. Adaptation moves runs to the left "
               "(fewer false alarms) but tends to move them up (later alarms); the LLM recommender adapts less "
               "and sits between static and heuristic adaptation."),
        P(f"The flip side is latency (Fig. 3). Adaptation raised mean alarm latency from "
          f"{ic['static']['mean_latency'][0]:.2f} to {ic['adaptive-heuristic']['mean_latency'][0]:.2f} iterations "
          f"(in the offline replication, from {off['lat_static'][0]:.2f} to {off['lat_adaptive'][0]:.2f}, higher in "
          f"{off['lat_up']} of {off['n']} seeds), because per-patient thresholds and 2-reading persistence delay "
          f"the first alarm of an episode; the LLM recommender's latency ({ic['adaptive-llm']['mean_latency'][0]:.2f}) "
          "stayed at the static level precisely because it adapted less. <b>Answer to RQ2:</b> adaptive norms "
          "reduced false alarms substantially without missing episodes, but the LLM recommender did not improve "
          "on a deterministic recommender and adapted more conservatively; neither reduced response time."),
        P("4.3 RQ3 – LLM decision under imperfect evidence", "h2"),
        figure(figs["decision_accuracy"], 0.6,
               "<b>Figure 4.</b> Accuracy of alarm verdicts (is the alarm real?). The Bayes-optimal classifier "
               "knows the generative model and serves only as a ceiling."),
    ]
    prof_names = {"stable": "No chronic disease", "copd": "COPD", "tachycardic": "Chronic tachycardia",
                  "low_bp": "Chronic hypotension"}
    rows = [["Patient profile", "Alarms", "Real", "False positives", "False negatives", "Accuracy"]]
    for prof in ("stable", "copd", "tachycardic", "low_bp"):
        cells = {(t, v): conf.get((prof, t, v), 0) for t in (True, False) for v in (True, False)}
        n = sum(cells.values())
        rows.append([prof_names[prof], str(n), str(cells[(True, True)] + cells[(True, False)]), str(cells[(False, True)]),
                     str(cells[(True, False)]), f"{(cells[(True, True)] + cells[(False, False)]) / n:.3f}"])
    rows.append(["All", str(n_dec), str(sum(n for (p, t, v_), n in conf.items() if t)), str(fp), str(fn), f"{acc_dec:.3f}"])
    story += [
        table(rows, [0.28, 0.12, 0.12, 0.17, 0.17, 0.14],
              "<b>Table 5.</b> Verdicts of the LLM decision agent per patient profile, reconstructed from the "
              "transcripts against the simulator's ground truth."),
        P(f"The LLM decision agent reached an accuracy of {ic['adaptive-llm-decision']['verdict_accuracy'][0]:.3f}, "
          f"against {ic['adaptive-heuristic']['verdict_accuracy'][0]:.3f} for the NEWS2 policy (paired Δ = "
          f"{ms(dec['verdict_accuracy']['delta'], '.3f')}, p = {dec['verdict_accuracy']['p']:.2f}) and "
          f"{ic['adaptive-llm-decision']['bayes_accuracy'][0]:.3f} for the Bayes ceiling. It traded a little "
          f"sensitivity ({ic['adaptive-llm-decision']['verdict_sensitivity'][0]:.2f} vs. 1.00) for specificity "
          f"({ic['adaptive-llm-decision']['verdict_specificity'][0]:.3f} vs. "
          f"{ic['adaptive-heuristic']['verdict_specificity'][0]:.3f}), with no net effect on false alarms "
          f"({fa['adaptive-llm-decision']:.1f} vs. {fa['adaptive-heuristic']:.1f}), and recognized episodes "
          f"slightly later ({ic['adaptive-llm-decision']['recognition_latency'][0]:.2f} vs. "
          f"{ic['adaptive-heuristic']['recognition_latency'][0]:.2f} iterations). Of its {n_dec} verdicts, {fp} were "
          f"false positives and {fn} false negatives (Table 5). Inspection of the errors shows that most false "
          "positives occurred when the evidence genuinely looked concerning—spurious findings or artifacts without "
          "a visible signal problem—and that the justifications were clinically coherent (e.g., attributing a "
          "systolic pressure of 88 mmHg to chronic hypotension). The gap to the ceiling reflects knowledge that "
          "no clinician has—the exact noise distributions—rather than a failure of reasoning. <b>Answer to "
          "RQ3:</b> under imperfect evidence, the LLM decision agent performed on par with an established "
          "clinical score, with interpretable justifications but no accuracy gain."),
        P("4.4 RQ4 – Engineering threats to validity", "h2"),
        P("Table 6 lists the problems found while building the study, how each was detected, what it would have "
          "done to the results, and the control adopted. Detection came from four sources: our own measurements, "
          "inspection of LLM transcripts, an independent automated code review performed by a separate LLM agent "
          "with no access to our reasoning, and—notably—the LLM-NormAuditor, whose report on an early run "
          "pointed out that alarms were recorded with vital signs that satisfied none of their norms."),
        table([
            ["#", "Threat", "Detected by", "Effect if unnoticed", "Control"],
            ["1", "Execution-order bias via mid-round state, mailbox order and a shared RNG", "measurement (agent "
             "permutations)", "97% of marketplace outcomes changed with agent order; first-acting seller made "
             "67% of sales (expected 33%)", "synchronous rounds; seeded canonical mailbox order; per-agent RNG; "
             "explicit conflict rule"],
            ["2", "Alarm stored the reading of the alarm iteration, not the triggering one", "LLM-NormAuditor",
             "62% of alarms carried vitals that triggered none of their norms; adaptation fed with wrong evidence",
             "store the triggering reading per norm"],
            ["3", "Ground truth, latency and specificity judged at alarm time (one iteration late)",
             "independent code review", "latency increase overstated about 2×; boundary alarms mislabeled",
             "judge by reading iteration"],
            ["4", "Bedside report leaked the ground truth", "design review", "decision reduced to keyword lookup",
             "stochastic findings; NEWS2 baseline; Bayes ceiling"],
            ["5", "Commands detected anywhere in free text", "LLM transcripts", "a refusal quoting "
             "\"Confirm_sale: 30\" counted as a confirmation and was sanctioned", "commands valid only as the "
             "whole message; environment feedback"],
            ["6", "Obligation fulfilled by an ineffective action; latch hid neglect", "independent code review",
             "a manager assigning all tasks to a departed developer: 0 tasks done, 0 violations",
             "count only effective assignments; re-arm obligations"],
            ["7", "Prompt and code disagreed on the meaning of persistence = 1", "independent code review",
             "following the prompt silently removed 2-reading persistence in LLM runs only", "0 = keep current, "
             "in prompt and code"],
            ["8", "Unpaired aggregation; fatal errors", "independent code review", "failed seeds dropped from "
             "one column only; an unknown task id aborted all paid runs", "paired tables; censoring; per-run "
             "fault tolerance"],
            ["9", "Uncontrolled cost", "dry run", "—", "dry-run estimate (US$ 4.76) vs. actual (US$ "
             f"{usage['estimated_cost_usd']:.2f}); budget cap; skip calls for agents with nothing to decide"],
            ["10", "<b>Study 2:</b> failed LLM calls defaulted silently to compliance", "independent code review",
             "a run in which every call failed was indistinguishable from the social strategy",
             "defaulted decisions counted; runs above 5% excluded and listed"],
            ["11", "A suppressed obligation fulfilled by an alarm for another norm of the same patient",
             "independent code review", "suppression rewarded as fulfillment, violation never recorded (2–3 per run)",
             "an alarm fulfills only the norms it declares"],
            ["12", "Harm counted per suppressed obligation", "independent code review",
             "up to three penalties per episode, also when the episode had already been alarmed",
             "one harm per episode, only if the suppression delayed recognition"],
            ["13", "Bounded working memory evicted old sanctions", "independent code review",
             "prompt section \"sanctions received\" omitted most of them", "permanent normative record"],
            ["14", "Detection draws not paired across conditions", "independent code review",
             "the same violation detected in one condition and not in another", "per-violation seeded draw"],
            ["15", "Sanction history in the prompt listed rewards", "prompt inspection",
             "misleading feedback to the LLM", "only sanctions, harms and confirmed outcomes shown"],
            ["16", "Pressured and opportunistic strategies indistinguishable", "offline pilot",
             "two strategies collapsed at a single sanction level", "sanction size added as a factor"],
            ["17", "Dry run underestimated the length of LLM justifications", "budget cap during the paid run",
             f"execution stopped in its last run; US$ {u2['cost_discarded']:.2f} of calls discarded",
             "results saved per run; missing run executed separately; offline runs checked identical; replay "
             "of transcripts reproduces every metric"],
        ], [0.04, 0.24, 0.15, 0.3, 0.27], "<b>Table 6.</b> Engineering threats to validity found while building "
                                         "the study, with their detection source, potential effect and control."),
        figure(figs["order_bias"], 0.62,
               "<b>Figure 5.</b> Share of runs whose outcome changes when the agent registration order is "
               "permuted, before and after introducing synchronous rounds (offline policies; marketplace: 50 seeds "
               "× 12 orders)."),
        table([["Component", "Calls", "Input tokens", "Output tokens", "Cost (US$)"]] + [
            [k, f"{v['calls']}", f"{v['in']:,}", f"{v['out']:,}", f"{v['usd']:.2f}"]
            for k, v in sorted(cost.items(), key=lambda kv: -kv[1]["usd"])] + [
            ["Total, Study 1", f"{usage['calls']}", f"{usage['input_tokens']:,}", f"{usage['output_tokens']:,}",
             f"{usage['estimated_cost_usd']:.2f}"],
            ["Study 2: LLM deliberation (incl. discarded run)", f"{u2['calls']}", f"{u2['input_tokens']:,}",
             f"{u2['output_tokens']:,}", f"{u2['cost']:.2f}"]],
            [0.36, 0.1, 0.18, 0.18, 0.18], "<b>Table 7.</b> Cost of the LLM runs by component and study (Claude "
                                         "Opus 5.5, effort low, US$ 4/20 per million input/output tokens)."),
        P("<b>Answer to RQ4:</b> threats 1–8 could each have produced a spurious difference between conditions "
          "or a distorted metric—several of them of the same order as the effects we measured—and threat 9 "
          "could have made the study unaffordable to replicate. Threats 10–16 of Study 2 were all found and fixed "
          "before any paid run; threat 17 affected only cost and was contained by per-run persistence. Synchronous rounds, pairing by seed, "
          "one-variable-at-a-time conditions, information parity in prompts, explicit protocol semantics, and "
          "transcript-level auditing were all necessary to obtain a fair comparison."),
    ]

    def dev_row(name, m, pending=False):
        # sem dado: XPTO se depende da rodada com LLM; "—" se a métrica não se aplica à condição
        f = vms if pending else (lambda pair, fmt=".1f": "—" if pair is None else ms(pair, fmt))
        return [name, f(m["false_alarms"]), f(m["suppressions"]), f(m["harmful_suppressions"]),
                f(m["harmed_episodes"]), f(m["mean_latency"], ".2f"), f(m["recognition_latency"], ".2f"),
                f(m["social_contribution"], ".3f"), f(m["individual_satisfaction"])]

    dev_table = [["Condition (p = 0.3)", "False alarms", "Suppressions", "Of real deterior.", "Harmed episodes",
                  "Alarm latency", "Recogn. latency", "Social contrib.", "Indiv. satisf."],
                 dev_row("Comply (social)", soc), dev_row("Adapt norms (Study 1)", a2),
                 dev_row("Selfish", sel), dev_row("Pressured", pres), dev_row("Opportunistic", opp),
                 dev_row("Rebellious", reb), dev_row("<b>LLM</b>", L[0.3], pending=True)]
    grid = [["Strategy", "Sanction ×"] + [f"p = {pv:g}" for pv in d2["detections"]]]
    for strat in ("selfish", "pressured", "opportunistic"):
        for sc in d2["scales"]:
            grid.append([strat, f"{sc:g}"] + [vms(s2[(strat, pv, sc)]["suppressions"], ".0f") for pv in d2["detections"]])
    grid.append(["<b>LLM</b>", "1"] + [vms(L[pv]["suppressions"], ".0f") for pv in d2["detections"]])

    def prec(m):
        if m["suppressions"] is None or m["justified_suppressions"] is None or not m["suppressions"][0]:
            return X()
        return f"{m['justified_suppressions'][0] / m['suppressions'][0]:.3f}"

    coh = [["Detection p", "Suppressions", "Share justified", "Harmed episodes", "Belief sensitivity",
            "Belief specificity", "Complied believing false", "Violated believing real"]]
    for pv in d2["detections"]:
        m = L[pv]
        coh.append([f"{pv:g}", vms(m["suppressions"]), prec(m), vms(m["harmed_episodes"]),
                    f"{bel[pv]['sens']:.3f}", f"{bel[pv]['spec']:.3f}", vms(m["comply_despite_believing_false"]),
                    vms(m["violate_despite_believing_real"])])

    theme_names = [("Clinical evidence: trend or stability", "trend"), ("Clinical evidence: artifact or signal",
                   "artifact"), ("The norm or the obligation", "norm"), ("Detection or audit", "detection"),
                   ("Sanction", "sanction"), ("Harm or harm penalty", "harm"), ("Patient safety", "safety"),
                   ("Alarm fatigue or satisfaction", "fatigue"), ("Uncertainty", "uncertainty")]
    cols = [("violated", None), ("complied, believed false", 0.3), ("complied, believed false", 0.7),
            ("complied, believed false", 1.0), ("complied, believed real", None)]
    themes = [["Theme mentioned", f"Violated (n = {th[cols[0]]['n']})"]
              + [f"Complied, believed false, p = {c[1]:g} (n = {th[c]['n']})" for c in cols[1:4]]
              + [f"Complied, believed real (n = {th[cols[4]]['n']})"]]
    for label, key in theme_names:
        themes.append([label] + [f"{100 * th[c][key]:.0f}%" for c in cols])

    reb_sat, soc_sat = reb["individual_satisfaction"][0], soc["individual_satisfaction"][0]
    sel_sat = sel["individual_satisfaction"][0]
    incentive_sentence = (
        f"At p = 0.3, rebellion {'did not pay' if reb_sat < soc_sat else 'paid'} for the agent itself: its individual "
        f"satisfaction was {reb_sat:.1f}, against {soc_sat:.1f} for the social agent and {sel_sat:.1f} for the selfish "
        f"one, while its social contribution was {reb['social_contribution'][0]:.2f}"
        + (" —harm penalties and lost rewards outweighed the satisfaction of avoided alarms." if reb_sat < soc_sat
           else " —the satisfaction of avoided alarms outweighed harm penalties, an incentive misalignment."))
    llm_vs_sel = (L3["false_alarms"][0] - sel["false_alarms"][0])
    story += [
        P("5 Results of Study 2", "h1"),
        P("5.1 RQ5 – Deviating from norms versus adapting them", "h2"),
        table(dev_table, [0.17, 0.1, 0.1, 0.1, 0.1, 0.09, 0.09, 0.1, 0.15],
              "<b>Table 10.</b> Study 2 at detection p = 0.3 and default sanction (3 paired seeds, mean ± s.d.). "
              "\"Of real deterior.\" counts suppressed obligations during a real deterioration; \"harmed "
              "episodes\" counts episodes whose recognition a suppression delayed."),
        figure(fig_dev, 0.95, "<b>Figure 6.</b> False alarms and alarm latency when norms are kept and complied "
               "with (Comply), adapted (Adapt, Study 1), or deviated from by an autonomous agent—selfish, "
               "opportunistic (Opport.), rebellious (Rebel) or LLM—at p = 0.3."),
        P(f"Keeping static norms and complying produced {soc['false_alarms'][0]:.1f} false alarms per run. Adapting "
          f"the norms (Study 1) reduced them to {a2['false_alarms'][0]:.1f} at the cost of a longer latency "
          f"({a2['mean_latency'][0]:.2f} vs. {soc['mean_latency'][0]:.2f} iterations). Deviation by a well-informed "
          f"agent did better on both counts: the selfish strategy left {sel['false_alarms'][0]:.1f} false alarms, "
          f"suppressed {sel['harmful_suppressions'][0]:.1f} obligations on real deterioration, harmed "
          f"{sel['harmed_episodes'][0]:.1f} episodes and kept latency at {sel['mean_latency'][0]:.2f}. This result "
          "hinges on the quality of the agent's belief: the NEWS2-based belief never judged a real "
          "deterioration false in this scenario. Uninformed deviation shows the other side—the rebellious agent "
          f"suppressed every regulated alarm, including {reb['harmful_suppressions'][0]:.1f} obligations on real "
          f"deterioration, harmed {reb['harmed_episodes'][0]:.1f} episodes per run and raised latency to "
          f"{reb['mean_latency'][0]:.2f} iterations; no episode was missed only because the critical norm is "
          "regimented. " + incentive_sentence),
        P(f"The LLM deliberative agent sits between compliance and well-informed deviation (Fig. 6). At p = 0.3 it "
          f"left {L3['false_alarms'][0]:.1f} false alarms per run—{pct(soc['false_alarms'][0], L3['false_alarms'][0])} "
          f"fewer than compliance, but {llm_vs_sel:.1f} more than the selfish agent and "
          f"{L3['false_alarms'][0] - a2['false_alarms'][0]:.1f} more than norm adaptation. It suppressed no "
          "obligation on real deterioration, harmed no episode, kept the latency of compliance "
          f"({L3['mean_latency'][0]:.2f} iterations) and a social contribution of "
          f"{L3['social_contribution'][0]:.2f}, and obtained an individual satisfaction of "
          f"{L3['individual_satisfaction'][0]:.1f}—above the social agent ({soc_sat:.1f}) and below the selfish "
          f"one ({sel_sat:.1f}). Its smaller effect has two sources, which Section 5.3 examines. First, its "
          f"beliefs were more cautious than the clinical score: it judged real {100 * bel[0.3]['false_as_real'] / bel[0.3]['n_false']:.0f}% "
          f"of the false alarms at p = 0.3, whereas the NEWS2-based belief judged real "
          f"{100 * (1 - news_spec):.0f}%. Second, even when it judged an alarm false it usually complied: it "
          f"violated only {100 * viol_share_03:.0f}% of the obligations it believed false. <b>Answer to RQ5:</b> "
          "deviation can substitute adaptation when the deviating agent's beliefs are accurate, and the "
          "regimented safety norm bounds the cost when they are not. The LLM deviated safely but conservatively: "
          "it reduced alarm fatigue by about a quarter without any clinical cost, which is less than norm "
          "adaptation or a score-guided selfish agent achieved."),
        P("5.2 RQ6 – Enforcement", "h2"),
        table(grid, [0.2, 0.14] + [0.66 / len(d2["detections"])] * len(d2["detections"]),
              "<b>Table 11.</b> Suppressions per run by strategy, detection probability and sanction scale (offline "
              "strategies: all scales; LLM: default scale)."),
        figure(fig_det, 0.6, "<b>Figure 9.</b> Share of regulated alarm obligations suppressed as a function of the "
               "detection probability (default sanction; mean of 3 seeds). With the default sanction, pressured and "
               "opportunistic agents behave identically. The LLM responds to enforcement like them but violates a "
               "much smaller share."),
        P(f"Selfish agents ignored enforcement: about {sel['suppressions'][0]:.0f} suppressions per run at every "
          "detection level and sanction scale. Opportunistic agents responded only to detection: they violated "
          "at p = 0.3 and complied at p ≥ 0.7, whatever the sanction. Pressured agents responded to the expected "
          "punishment: with the default sanction they violated at p = 0.3 and complied at p ≥ 0.7; with a "
          "sanction three times larger they complied even at p = 0.3; with a sanction five times smaller they "
          f"violated at every detection level. The LLM suppressed {L[0.3]['suppressions'][0]:.1f}, "
          f"{L[0.7]['suppressions'][0]:.1f} and {L[1.0]['suppressions'][0]:.1f} alarms per run at p = 0.3, 0.7 and "
          f"1.0—{sup_rate[0.3]:.1f}%, {sup_rate[0.7]:.1f}% and {sup_rate[1.0]:.1f}% of its regulated obligations "
          "(Fig. 9). Its response to enforcement therefore has the shape of the pressured and opportunistic "
          "strategies, which make the same prediction under the default sanction; because the LLM was run only "
          "with that sanction, our design cannot tell which of the two it resembles more, and its justifications "
          f"cite both the sanction ({100 * th[('violated', None)]['sanction']:.0f}% of violations) and the "
          f"detection probability ({100 * th[('violated', None)]['detection']:.0f}%)."),
        P("The difference lies in the level. A pressured agent violates every obligation it believes false when "
          "the expected sanction is low: at p = 0.3, suppressing yields satisfaction 3, against an expected "
          "sanction of 0.3 × 5 = 1.5 and the lost reward of 1. The LLM often reasoned in the same terms "
          "(\"the expected cost of the sanction, 0.3 × 5 = 1.5, is acceptable\"), but it also priced a risk the "
          "pressured strategy ignores: that its belief could be wrong. If a real deterioration costs 20, "
          "suppressing pays off only when the probability that the alarm is real is below 2.5%, and the LLM "
          "said so explicitly (\"since harm costs 20, against a net gain of about 2 for not sounding, a low "
          "probability of real deterioration is enough to justify the alarm\"; quotations translated from "
          "Portuguese). Such reasoning is a rational response to uncertainty, but it was conservative relative to "
          f"the LLM's own accuracy: of the {conf2[0.3][(False, False)] + conf2[0.3][(False, True)]} obligations "
          f"it believed false at p = 0.3 (three seeds), only {conf2[0.3][(False, True)]} was a real deterioration. "
          "Experienced sanctions did not deter it either: among obligations it believed false at p = 0.3, it "
          f"violated {100 * learn['before']:.0f}% before its first detected sanction (n = {learn['before_n']}) and "
          f"{100 * learn['after']:.0f}% afterwards (n = {learn['after_n']}). This is consistent with the design—"
          "the detection probability is stated in the prompt, so a sanction carries no new information—but it "
          "means the normative record in the prompt did not act as a learning signal. <b>Answer to RQ6:</b> "
          "enforcement separated the classical strategies exactly as their definitions predict. The LLM responded "
          "to detection like a pressured or opportunistic agent, with a steep drop between p = 0.3 and p = 0.7, "
          "but it violated selectively and far below the level that expected-value reasoning on its own beliefs "
          "would justify."),
        P("5.3 RQ7 – Are the LLM's violations justified and coherent?", "h2"),
        table(coh, [0.09, 0.14, 0.1, 0.11, 0.12, 0.12, 0.16, 0.16],
              "<b>Table 12.</b> LLM deliberation by detection probability (3 seeds; mean ± s.d. per run where "
              "applicable). Belief sensitivity and specificity compare the stated belief (\"the deterioration is "
              "real\") with the ground truth, recovered by replaying the transcripts."),
        P(f"<b>Justification of violations.</b> All of the LLM's suppressions were justified at every detection "
          f"level (share justified = {prec(L3)}): every alarm it suppressed was false, and it harmed no patient. "
          f"Its stated beliefs were highly sensitive ({bel[0.3]['sens']:.3f} at p = 0.3) but not specific "
          f"({bel[0.3]['spec']:.3f}): only in {sum(c[(False, True)] for c in conf2.values())} of "
          f"{sum(sum(c.values()) for c in conf2.values())} deliberations across all runs did it judge a real "
          "deterioration false—and in each case it complied anyway—whereas it judged about a third of the false "
          "alarms real. In Study 1, the LLM decision agent, asked only whether an alarm was real, had traded "
          "sensitivity for specificity; asked the same question as a deliberating agent that bears a harm "
          "penalty, the same model leaned toward caution. Stated beliefs thus depend on the role and incentives "
          "under which they are elicited."),
        P(f"<b>Coherence between belief and decision.</b> The LLM never violated an obligation while declaring "
          f"the deterioration real, and it complied while declaring the alarm false in "
          f"{L3['comply_despite_believing_false'][0]:.0f}, {L[0.7]['comply_despite_believing_false'][0]:.0f} and "
          f"{L[1.0]['comply_despite_believing_false'][0]:.0f} cases per run at p = 0.3, 0.7 and 1.0 (Table 12). "
          "Decision and belief are therefore coherent in the weak sense that no decision contradicts the stated "
          "belief. A stronger test is possible because the three detection levels share the same seeds, patients "
          f"and alarms: the {shift['n']} obligations were decided under p = 0.3 and again under p = 1.0, with "
          "identical clinical evidence. If the beliefs were independent of the incentives, changes between the "
          "two conditions would be due to sampling noise and would be symmetric. They were not: "
          f"{shift['to_false']} beliefs changed from \"real\" to \"false\" and only {shift['to_real']} from "
          f"\"false\" to \"real\" (exact McNemar test, p = {shift['p']:.4f}). When suppressing was attractive "
          "(p = 0.3), the LLM more often declared the deterioration real—the belief that licenses compliance; when "
          "detection was certain and compliance was settled by the sanction, it declared the alarm false more "
          "freely and complied \"because the violation would be detected with certainty\". The stated belief "
          "follows the decision context, which indicates that the justification partly rationalizes the "
          "decision rather than reporting an independent clinical judgment."),
        table(themes, [0.25, 0.13, 0.155, 0.155, 0.155, 0.155],
              "<b>Table 13.</b> Themes mentioned in the LLM's justifications, by decision (all 2,115 decisions of "
              "the nine runs; keyword coding in Portuguese and English, so a justification can mention several "
              "themes)."),
        P("<b>Content of the justifications.</b> Table 13 shows what the LLM cited. Violations rested on clinical "
          f"evidence that the alarm was false—stability of the trend ({100 * th[('violated', None)]['trend']:.0f}%), "
          f"artifacts ({100 * th[('violated', None)]['artifact']:.0f}%)—and on alarm fatigue "
          f"({100 * th[('violated', None)]['fatigue']:.0f}%); they rarely invoked patient safety "
          f"({100 * th[('violated', None)]['safety']:.0f}%) and never uncertainty, "
          "e.g., \"heart rate of 120 is within the usual range of this patient with chronic sinus tachycardia "
          "[…]; not sounding avoids alarm fatigue; the expected cost of the sanction (0.3 × 5 = 1.5) is "
          "acceptable\". Compliance despite believing the alarm false was justified mainly by safety "
          f"({100 * th[('complied, believed false', 0.3)]['safety']:.0f}% at p = 0.3), harm "
          f"({100 * th[('complied, believed false', 0.3)]['harm']:.0f}%) and residual uncertainty "
          f"({100 * th[('complied, believed false', 0.3)]['uncertainty']:.0f}%); the share that cited the "
          f"detection probability rose from {100 * th[('complied, believed false', 0.3)]['detection']:.0f}% at "
          f"p = 0.3 to {100 * th[('complied, believed false', 1.0)]['detection']:.0f}% at p = 1.0, when certain "
          "detection became the stated reason to comply. Compliance with alarms believed real was justified "
          "almost only by clinical evidence and safety; incentives were rarely mentioned. Finally, "
          f"{100 * js['english']:.0f}% of the justifications were written in English although every prompt was in "
          "Portuguese, a reminder that output conventions are not fully controlled by the prompt. "
          "<b>Answer to RQ7:</b> the LLM's violations were all justified ex post, and its decisions never "
          "contradicted its stated beliefs. Its beliefs, however, were cautious and moved with the enforcement "
          "level for identical evidence, so its justifications are informative about the factors it weighed "
          "but cannot be read as independent evidence about the patient."),
    ]

    # ------------------------------------------------------------- 5 implications
    story += [
        P("6 Implications", "h1"),
        P("6.1 For LLM-driven norm adaptation", "h2"),
        P("Our results separate two claims that are easily conflated: that <i>adaptive norms</i> help, and that "
          "<i>LLMs</i> make adaptation better. The first was clearly supported—per-patient thresholds and "
          "persistence removed most false alarms without missed episodes. The second was not: a deterministic "
          "recommender did better. The LLM recommender's caution is understandable—its evidence mixed confirmed "
          "outcomes with unconfirmed verdicts without saying which was which—and suggests a concrete design "
          "rule for ANA-ML 2.0: evidence passed to an LLM-NormRecommender should carry its <i>provenance</i> "
          "(confirmed outcome versus agent verdict). We also recommend that latency be reported alongside false "
          "alarms, since the two trade off, and that safety bounds remain deterministic, as in our validator."),
        P("6.2 For LLM decision support", "h2"),
        P("Matching a validated clinical score is a meaningful but modest result. The LLM's distinctive "
          "contribution was not accuracy but explanation: each verdict came with a justification a clinician can "
          "check. Evaluations of LLM decision agents should therefore include a strong domain baseline and an "
          "explicit ceiling; without them, an accuracy of 0.8 is uninterpretable."),
        P("6.3 For engineering LLM-based MAS simulations", "h2"),
        bullets([
            "Use synchronous rounds and seeded canonical message ordering; test order invariance explicitly.",
            "Give every LLM component a deterministic counterpart and change one component per condition.",
            "Never let observations encode the ground truth; model noise explicitly and report a ceiling.",
            "Define protocol commands so that mentioning a command is distinguishable from issuing it, and give "
            "agents feedback when an action has no effect.",
            "Make obligations count only effective actions; decide explicitly whether they re-arm.",
            "Pair results by seed, censor unfinished runs, and treat any single API failure as recoverable.",
            "Estimate cost with a dry run before spending, and keep full transcripts for auditing.",
        ]),
        P("6.4 The auditor as a transparency mechanism", "h2"),
        P("The LLM-NormAuditor was the most useful LLM component in practice. In an early run it identified a "
          "real measurement defect (Table 6, #2). In the final run it also raised a false suspicion—three metrics "
          "with identical values, which we verified to be an arithmetic coincidence—showing that its reports are "
          "valuable prompts for human inspection rather than verdicts."),
        P("6.5 Deviating from norms versus adapting them", "h2"),
        P("Study 2 suggests that autonomy over compliance is a lever comparable to norm adaptation—and, offline, "
          "a stronger one—provided two design conditions hold. First, safety-critical norms must be regimented: "
          "every harm we observed was bounded by the critical norm, which no strategy could violate. Second, "
          "incentives must keep individual satisfaction aligned with social contribution. With our a priori values "
          f"they did ({'rebellion' if reb_sat < soc_sat else 'not even rebellion'} "
          f"{'was the least satisfying strategy' if reb_sat < soc_sat else 'was penalized enough'}), but the balance "
          "depends on the harm penalty and on enforcement, and must be checked whenever they change."),
        P("6.6 For LLM deliberation in ANA-ML 2.0", "h2"),
        P("The LLM was a <i>safe</i> deliberative agent: under a regimented safety norm and an explicit harm "
          "penalty, it violated only alarms that were false and never delayed the recognition of a "
          "deterioration. It was not an <i>effective</i> one: its caution left most of the alarm fatigue in "
          "place, and it used its own accurate beliefs far less than expected-value reasoning would allow. For "
          "regulated, non-critical norms with a regimented safety net, delegating compliance decisions to an LLM "
          "is therefore defensible, but it should not be expected to outperform a well-calibrated deterministic "
          "rule. Three design rules follow for ANA-ML 2.0 and JSAN:"),
        bullets([
            "<b>Separate Analyze from Decision.</b> ANA-BDI already distinguishes the stage that forms judgments "
            "from the stage that chooses (Fig. 7). Our results show why this separation should be kept when an LLM "
            "fills the deliberation hot spot: when one call both judges the alarm and decides, the stated belief "
            "follows the incentive. Beliefs should be elicited in a call that does not see rewards, sanctions or "
            "detection probabilities, and the decision should consume them.",
            "<b>Audit justifications counterfactually.</b> A justification is a useful account of the factors the "
            "model weighed, but not independent evidence. Auditors such as the LLM-NormAuditor should compare "
            "decisions on the same evidence under different incentives—as our paired design did—rather than "
            "assess each justification on its own.",
            "<b>Make calibration explicit.</b> The LLM priced the harm penalty correctly in words but acted as if "
            "its beliefs were less reliable than they were. Feeding back confirmed outcomes of its own suppressions "
            "did not change its behavior; giving it calibrated probabilities, or applying a deterministic "
            "expected-value rule to its stated beliefs, are alternatives worth testing.",
        ]),
    ]

    # --------------------------------------------------------- 6 threats to validity
    story += [
        P("7 Threats to Validity", "h1"),
        P("<b>Construct validity.</b> The ICU scenario is synthetic: physiology is reduced to Gaussian vital "
          "signs with linear deterioration, and the bedside-findings model and its probabilities were designed by "
          "the authors. The decision baseline is a modified NEWS2 score, not the official instrument. The "
          "marketplace and project scenarios are small and stylized."),
        P("<b>Internal validity.</b> We used a single model, at a single effort level, with one run per seed; LLM "
          "outputs are stochastic and prompt-sensitive, and other prompts could change the results. The "
          "heuristic baselines differ in strength across scenarios (weak in the marketplace, strong in project "
          "management). Engineering defects were mitigated by the controls in Table 6 and by 78 automated tests, "
          "including order-invariance and no-leakage tests, but further defects cannot be excluded."),
        P("<b>Study 2.</b> The compliance strategies are our operationalizations of qualitative definitions [6]; "
          "the Motivation, Satisfaction, reward, sanction and harm values were fixed a priori and other values could "
          "change the balance between strategies; and the NEWS2-based belief used by the offline strategies was "
          "never wrong about real deteriorations in this scenario, which favors them. Each obligation is "
          "decided once, and obligations suppressed in the last two iterations never expire. The LLM was run "
          "only with the default sanction, so pressured and opportunistic behavior cannot be distinguished for it, "
          "and with one run per seed and detection level, so its sampling variability is confounded with the "
          "seed. The analysis of belief changes treats the decisions on each obligation as paired observations; "
          "decisions within a run are not fully independent, since the prompt carries the agent's normative "
          "record. The themes in Table 13 were coded by keywords, not by human annotators, and are indicative "
          "only."),
        P("<b>External validity.</b> Results concern one LLM, three scenarios and simulated data; they should not "
          "be generalized to real clinical settings or to other models without replication."),
        P("<b>Conclusion validity.</b> With three paired seeds, no difference can reach conventional significance "
          "(minimum exact p = 0.25), and effect sizes are imprecise. We therefore report all findings as "
          "exploratory, together with per-seed data (Figs. 2–3)."),
    ]

    # ------------------------------------------------------------- 7 conclusion
    story += [
        P("8 Concluding Remarks", "h1"),
        P("We presented a controlled, exploratory comparison of LLM-based and deterministic components in "
          "adaptive normative multi-agent systems. LLM agents negotiated better; adaptive norms reduced ICU false "
          "alarms; but an LLM did not improve norm recommendation or alarm triage over strong deterministic "
          "baselines, and adaptation increased latency. Building a fair comparison required controlling "
          "seventeen engineering threats to validity, two of which were revealed by the LLM-NormAuditor. In Study 2, agents "
          "decided whether to comply: well-informed deviation reduced false alarms more than norm adaptation, "
          "uninformed deviation harmed patients within the bounds of a regimented norm, and enforcement separated "
          "the classical strategies as predicted. The LLM deliberative agent was safe but conservative: it "
          f"suppressed {sup_rate[0.3]:.0f}% of regulated alarms when detection was unlikely and almost none when "
          "it was certain, all of them false, and harmed no patient; yet its stated beliefs shifted with the "
          "detection probability for identical evidence, so its justifications partly rationalize its decisions. "
          "As future work, "
          "we plan to (i) replicate both studies with more seeds, other models and effort levels; (ii) give the "
          "recommender label provenance; (iii) evaluate the LLM validator as a separate condition; (iv) separate "
          "belief elicitation from the compliance decision and run the LLM under several sanction sizes; (v) study "
          "populations of deliberative agents and the canonical ANA rescue scenario; and (vi) validate the approach "
          "on real data. The platform, data and "
          "transcripts are available in the <i>llm-mas</i> repository [link to be added]."),
        P("<b>Acknowledgments.</b> [Funding: CAPES, CNPq and NSERC, to be confirmed.] [Disclosure of AI assistance "
          "in software development and drafting, according to the venue's policy.]"),
    ]

    # ------------------------------------------------------------- referências
    refs = [
        "N. Nascimento, P. Alencar, and D. Cowan. Self-Adaptive Large Language Model (LLM)-Based Multiagent "
        "Systems. arXiv:2307.06187, 2023.",
        "M. Viana, P. Alencar, E. Guimarães, E. Cirilo, and C. Lucena. Creating a Modeling Language Based on a New "
        "Metamodel for Adaptive Normative Software Agents. <i>IEEE Access</i>, 10:13974–13996, 2022.",
        "M. Viana, P. Alencar, and C. Lucena. A Modeling Language for Adaptive Normative Agents. In <i>EUMAS 2016 "
        "and AT 2016</i>, LNCS 10207, pp. 40–48. Springer, 2017.",
        "M. L. Viana, P. Alencar, E. T. Guimarães, F. J. P. Cunha, D. Cowan, and C. J. P. Lucena. JSAN: A Framework "
        "to Implement Normative Agents. In <i>Proc. SEKE</i>, pp. 660–665, 2015.",
        "M. Viana, E. Cirilo, P. Alencar, D. Cowan, and C. Lucena. ANA-ML 2.0: Supporting the Modelling of "
        "Multi-Agent Systems with LLM. Manuscript in preparation.",
        "F. López y López, M. Luck, and M. d'Inverno. Constraining Autonomy through Norms. In <i>Proc. AAMAS</i>, "
        "pp. 674–681, 2002.",
        "Royal College of Physicians. <i>National Early Warning Score (NEWS) 2: Standardising the Assessment of "
        "Acute-Illness Severity in the NHS</i>. London: RCP, 2017.",
        "G. Beydoun, G. Low, B. Henderson-Sellers, H. Mouratidis, J. J. Gomez-Sanz, J. Pavón, and C. Gonzalez-Perez. "
        "FAML: A Generic Metamodel for MAS Development. <i>IEEE Trans. Softw. Eng.</i>, 35(6):841–863, 2009.",
        "V. T. da Silva and C. J. P. de Lucena. From a Conceptual Framework for Agents and Objects to a Multi-Agent "
        "System Modeling Language. <i>Auton. Agents Multi-Agent Syst.</i>, 9(1/2):145–189, 2004.",
        "R. de Lemos et al. Software Engineering for Self-Adaptive Systems: A Second Research Roadmap. In "
        "<i>Software Engineering for Self-Adaptive Systems II</i>, pp. 1–32. Springer, 2013.",
        "J. O. Kephart and D. M. Chess. The Vision of Autonomic Computing. <i>Computer</i>, 36(1):41–50, 2003.",
    ]
    story += [P("References", "h1")] + [P(f"[{i}] {r}", "ref") for i, r in enumerate(refs, 1)]
    if not d2["llm_available"]:
        story += [P("Appendix A – Pending data", "h1"),
                  P("Values shown as " + X() + " depend on the Study 2 LLM runs, which have not been executed. "
                    "Running <tt>llm-mas deliberation --llm claude --effort low --out results/phase2-llm</tt> and "
                    "regenerating this PDF fills all numeric XPTO automatically: Tables 10–12, Figure 6, and the "
                    "numbers in Sections 5.1–5.3. Bracketed XPTO items require writing after the runs: the abstract "
                    "and introduction summaries of the LLM result, the answers to RQ5–RQ7, the qualitative analysis "
                    "of the LLM's justifications (Section 5.3), Section 6.5, the conclusion, and the actual cost "
                    "(Section 3.7).")]
    return story


def build() -> Path:
    import build_tex  # mesmo conteúdo e numeração do main.tex

    story = build_tex.to_flowables(build_tex.capture_story())
    out = HERE / "paper.pdf"

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Sans", 7)
        canvas.setFillColor(INK2)
        canvas.drawString(2.1 * cm, 1.2 * cm, "Draft v3 — LLMs in adaptive normative MAS: adaptation and compliance")
        canvas.drawRightString(A4[0] - 2.1 * cm, 1.2 * cm, str(doc.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=2.1 * cm, rightMargin=2.1 * cm, topMargin=2 * cm,
                            bottomMargin=2 * cm, title="Do LLMs Improve Adaptive Normative Agents? (draft v3)",
                            author="Marx Viana et al.")
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return out


if __name__ == "__main__":
    print(build())
