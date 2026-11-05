"""Gera paper/latex/main.tex (modelo IEEE Access, classe ieeeaccess) a partir do
mesmo conteúdo de build_paper.py, para compilar no Overleaf.

    .venv/bin/python paper/build_tex.py

Os helpers de build_paper (P, bullets, table, figure, X) são trocados por versões
que registram o conteúdo; aqui ele é convertido para LaTeX. Referências cruzadas
("Table 6", "Section 4.4", "[2, 3]") viram \\ref e \\cite, então a numeração
segue a ordem de aparição, como exige o IEEE.
"""

from __future__ import annotations

import html
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_paper as BP  # noqa: E402

OUT = HERE / "latex"

# ------------------------------------------------------------- captura do conteúdo


def _P(text, style="p"):
    return ("p", style, text)


def _bullets(items):
    return ("bullets", items)


def _table(rows, widths, caption, bold_first_col=False):
    return ("table", rows, widths, caption, bold_first_col)


def _figure(path, width_frac, caption):
    return ("figure", Path(path), width_frac, caption)


def _X(text="XPTO"):
    return f"<font color='red'><b>{text}</b></font>"


def capture_story() -> list:
    """Conteúdo de build_paper como tuplas, renumerado pela ordem de aparição."""
    saved = BP.P, BP.bullets, BP.table, BP.figure, BP.X
    BP.P, BP.bullets, BP.table, BP.figure, BP.X = _P, _bullets, _table, _figure, _X
    try:
        story = BP.make_story()
    finally:
        BP.P, BP.bullets, BP.table, BP.figure, BP.X = saved
    return renumber(story)


REF = re.compile(r"\b(Tables?|Figs?\.|Figures?) (\d+)((?:\s*(?:–|,|and)\s*\d+)*)")


def renumber(story: list) -> list:
    """Tabelas e figuras numeradas na ordem em que aparecem (exigência do IEEE)."""
    new = {"Table": {}, "Figure": {}}
    for item in story:
        if item[0] in ("table", "figure"):
            m = CAPTION.match(item[3])
            new[m.group(1)][m.group(2)] = str(len(new[m.group(1)]) + 1)

    def fix(text: str) -> str:
        def sub(m):
            kind = "Table" if m.group(1).startswith("Table") else "Figure"
            return m.group(1) + " " + re.sub(r"\d+", lambda n: new[kind][n.group(0)], m.group(2) + m.group(3))
        return REF.sub(sub, text)

    out = []
    for item in story:
        if item[0] == "p" and item[1] != "ref":
            out.append(("p", item[1], fix(item[2])))
        elif item[0] == "bullets":
            out.append(("bullets", [fix(t) for t in item[1]]))
        elif item[0] == "table":
            out.append(("table", [[fix(str(c)) for c in row] for row in item[1]], item[2], fix(item[3]), item[4]))
        elif item[0] == "figure":
            out.append(("figure", item[1], item[2], fix(item[3])))
        else:
            out.append(item)
    return out


def to_flowables(story: list) -> list:
    """Converte as tuplas de volta nos flowables do reportlab (PDF de prévia)."""
    kinds = {"p": lambda st, t: BP.P(t, st), "bullets": BP.bullets, "table": BP.table, "figure": BP.figure}
    return [kinds[item[0]](*item[1:]) for item in story]


# ------------------------------------------------------------- marcação → LaTeX

SYMBOLS = {"≥": r"$\geq$", "≤": r"$\leq$", "±": r"$\pm$", "×": r"$\times$", "Δ": r"$\Delta$",
           "→": r"$\rightarrow$", "≈": r"$\approx$", "−": r"$-$", "•": r"\textbullet{}", "…": r"\ldots{}"}
ESCAPE = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "#": r"\#", "$": r"\$", "_": r"\_",
          "{": r"\{", "}": r"\}", "<": r"$<$", ">": r"$>$", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
TAGS = {"b": r"\textbf{", "i": r"\emph{", "sub": r"\textsubscript{", "super": r"\textsuperscript{",
        "tt": r"\texttt{", "font": r"\textcolor{red}{"}


def _escape(text: str) -> str:
    text = html.unescape(text)
    out = "".join(ESCAPE.get(c, c) for c in text)
    for k, val in SYMBOLS.items():
        out = out.replace(k, val)
    return out


def _crossrefs(s: str) -> str:
    """Referências numéricas → \\ref/\\cite, depois da conversão (números já são texto)."""
    num_list = r"(\d+(?:\.\d+)?)((?:\s*(?:–|,|and)\s*\d+(?:\.\d+)?)*)"

    def refs(prefix, kind):
        def sub(m):
            nums = re.findall(r"\d+(?:\.\d+)?", m.group(1) + m.group(2))
            seps = re.findall(r"\s*(?:–|,|and)\s*", m.group(2))
            parts = [f"\\ref{{{kind}:{nums[0]}}}"]
            for sep, n in zip(seps, nums[1:]):
                parts.append(sep.replace("–", "--") + f"\\ref{{{kind}:{n}}}")
            prefix_txt = m.group(0)[: m.start(1) - m.start(0)]
            if kind == "fig":  # IEEE: sempre "Fig." no texto
                prefix_txt = "Figs. " if re.match(r"Figs|Figures", prefix_txt) else "Fig. "
            return prefix_txt.replace(" ", "~") + "".join(parts)
        return re.compile(prefix + num_list), sub

    for prefix, kind in ((r"\bTables? ", "tab"), (r"\bFig(?:s?\.|ures?) ", "fig"), (r"\bSections? ", "sec")):
        rx, sub = refs(prefix, kind)
        s = rx.sub(sub, s)
    s = re.sub(r"\[(\d+(?:,\s*\d+)*)\]", lambda m: "\\cite{" + ",".join(BIB_KEYS[int(n)] for n in
                                                                       m.group(1).split(",")) + "}", s)
    return s


def tex(text: str, refs: bool = True) -> str:
    text = re.sub(r'"([^"<>]*)"', r"``\1''", text)
    out, stack = [], []
    for part in re.split(r"(<[^>]+>)", text):
        m = re.fullmatch(r"<(/?)(\w+)[^>]*?(/?)>", part)
        if not m:
            out.append(_escape(part))
        elif m.group(2) == "br":
            out.append(r"\\ ")
        elif m.group(1):
            out.append("}")
            stack.pop()
        else:
            out.append(TAGS[m.group(2)])
            stack.append(m.group(2))
    assert not stack, f"tag sem fechamento em: {text[:80]}"
    s = "".join(out)
    return _crossrefs(s) if refs else s


# número da referência em build_paper → chave em latex/references.bib
BIB_KEYS = {1: "nascimento2023selfadaptive", 2: "viana2022creating", 3: "viana2017modeling", 4: "viana2015jsan",
            5: "viana2025anaml2", 6: "lopez2002constraining", 7: "rcp2017news2", 8: "beydoun2009faml",
            9: "dasilva2004conceptual", 10: "delemos2013roadmap", 11: "kephart2003vision"}

CAPTION = re.compile(r"^<b>(Table|Figure) (\d+)\.</b>\s*")


def _caption(caption: str) -> tuple[str, str]:
    m = CAPTION.match(caption)
    assert m, caption
    return ("tab" if m.group(1) == "Table" else "fig") + ":" + m.group(2), caption[m.end():]


# ------------------------------------------------------------- blocos


def _table_tex(rows, widths, caption, bold_first_col) -> str:
    label, cap = _caption(caption)
    ncol = len(rows[0])
    wide = ncol > 3
    env = "table*" if wide else "table"
    width = r"\textwidth" if wide else r"\columnwidth"
    pad = 2 * ncol * 0.06  # \tabcolsep = 0.06cm por lado (abaixo)
    total = sum(widths)
    spec = "".join(f">{{\\raggedright\\arraybackslash}}p{{\\dimexpr{w / total:.3f}{width}-{pad / ncol:.2f}cm\\relax}}"
                   for w in widths)
    lines = [f"\\begin{{{env}}}[!t]", r"\centering", f"\\caption{{{tex(cap)}}}", f"\\label{{{label}}}",
             r"\footnotesize", r"\setlength{\tabcolsep}{0.06cm}", r"\renewcommand{\arraystretch}{1.15}",
             f"\\begin{{tabular}}{{@{{}}{spec}@{{}}}}", r"\hline"]
    for r, row in enumerate(rows):
        cells = [tex(str(c)) for c in row]
        if r == 0:
            cells = [f"\\textbf{{{c}}}" for c in cells]
        elif bold_first_col:
            cells[0] = f"\\textbf{{{cells[0]}}}"
        lines.append(" & ".join(cells) + r" \\" + (r" \hline" if r in (0, len(rows) - 1) else ""))
    lines += [r"\end{tabular}", f"\\end{{{env}}}", ""]
    return "\n".join(lines)


def _figure_tex(path: Path, frac: float, caption: str) -> str:
    label, cap = _caption(caption)
    (OUT / "figures").mkdir(parents=True, exist_ok=True)
    # IEEE: gráficos vetoriais quando existem; arquivos nomeados autor + número da figura
    src = path.with_suffix(".pdf") if path.with_suffix(".pdf").exists() else path
    name = f"viana{label.split(':')[1]}{src.suffix}"
    shutil.copy(src, OUT / "figures" / name)
    wide = frac >= 0.8
    env = "figure*" if wide else "figure"
    width = f"{min(frac, 0.95):.2f}\\textwidth" if wide else r"\columnwidth"
    return "\n".join([f"\\begin{{{env}}}[!t]", r"\centering",
                      f"\\includegraphics[width={width}]{{figures/{name}}}",
                      f"\\caption{{{tex(cap)}}}", f"\\label{{{label}}}", f"\\end{{{env}}}", ""])


def render(story) -> str:
    front = {"title": None, "abstract": None, "keywords": None}
    body, refs = [], []
    for item in story:
        kind = item[0]
        if kind == "p":
            _, style, text = item
            if style == "title":
                front["title"] = tex(text, refs=False)
            elif style == "authors":
                continue  # autores vêm do modelo IEEE Access
            elif style == "abs" and text.startswith("<b>Abstract.</b>"):
                front["abstract"] = tex(text[len("<b>Abstract.</b>"):].strip())
            elif style == "abs":
                front["keywords"] = tex(re.sub(r"^<b>Keywords:</b>\s*", "", text)).rstrip(".")
            elif style == "ref":
                continue  # referências vêm de references.bib (estilo IEEEtran)
            elif style in ("h1", "h2"):
                m = re.match(r"(\d+(?:\.\d+)?)\s+(.*)", text)
                if text == "References" or text.startswith("Appendix"):
                    if text.startswith("Appendix"):
                        body.append(f"\\section*{{{tex(text)}}}")
                    continue
                cmd = "section" if style == "h1" else "subsection"
                body.append(f"\\{cmd}{{{tex(m.group(2))}}}\\label{{sec:{m.group(1)}}}")
            elif text.startswith("<b>Acknowledgments.</b>"):  # IEEE: seção sem número, no singular
                body.append("\\section*{Acknowledgment}\n" + tex(text[len("<b>Acknowledgments.</b>"):].strip()) + "\n")
            else:
                body.append(tex(text) + "\n")
        elif kind == "bullets":
            body.append("\\begin{itemize}\n" + "\n".join(f"\\item {tex(t)}" for t in item[1]) + "\n\\end{itemize}\n")
        elif kind == "table":
            body.append(_table_tex(*item[1:]))
        elif kind == "figure":
            body.append(_figure_tex(*item[1:]))
    return TEMPLATE.format(title=front["title"], abstract=front["abstract"], keywords=front["keywords"],
                           body="\n".join(body))


TEMPLATE = r"""\documentclass{{ieeeaccess}}
\usepackage{{cite}}
\usepackage{{amsmath,amssymb,amsfonts}}
\usepackage{{algorithmic}}
\usepackage{{graphicx}}
\usepackage{{textcomp}}
\usepackage{{xcolor}}
\usepackage{{array}}
\emergencystretch=3em

% Gerado por paper/build_tex.py a partir dos resultados em results/; não editar números à mão.
\begin{{document}}

\history{{Date of publication xxxx 00, 0000, date of current version xxxx 00, 0000.}}
\doi{{10.1109/ACCESS.2017.DOI}}

\title{{{title}}}
\author{{\uppercase{{Marx Viana}}\authorrefmark{{1}},
\uppercase{{Elder Cirilo}}\authorrefmark{{2}},
\uppercase{{Paulo Alencar}}\authorrefmark{{3}},
\uppercase{{Donald Cowan}}\authorrefmark{{3}},
\uppercase{{Carlos Lucena}}\authorrefmark{{1}}}}

\address[1]{{Pontifical Catholic University of Rio de Janeiro, Rio de Janeiro, Brazil \{{mleles, lucena\}}@inf.puc-rio.br}}
\address[2]{{Federal University of São João del Rei, Minas Gerais, Brazil \{{elder\}}@ufsj.edu.br}}
\address[3]{{David R. Cheriton School of Computer Science, University of Waterloo, Waterloo, Ontario, Canada \{{palencar, dcowan\}}@uwaterloo.ca}}

\tfootnote{{This work was supported by the Brazilian funding agencies CAPES, CNPq and the Natural Sciences and Engineering Research Council of Canada (NSERC)}}

\markboth
{{Viana \headeretal: Do LLMs Improve Adaptive Normative Agents?}}
{{Viana \headeretal: Do LLMs Improve Adaptive Normative Agents?}}

\corresp{{Corresponding author: Marx Viana (e-mail: mleles@inf.puc-rio.br).}}

\begin{{abstract}}
{abstract}
\end{{abstract}}

\begin{{keywords}}
{keywords}
\end{{keywords}}

\titlepgskip=-15pt

\maketitle

{body}

\bibliographystyle{{IEEEtran}}
\bibliography{{IEEEabrv,references}}

\input{{bios}}

\EOD

\end{{document}}
"""


def build() -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    text = render(capture_story())
    labels = set(re.findall(r"\\label\{([^}]+)\}", text))
    missing = sorted(set(re.findall(r"\\ref\{([^}]+)\}", text)) - labels)
    assert not missing, f"referências sem rótulo: {missing}"
    odd = sorted({c for c in text if ord(c) > 0x17F and c not in "–—"})  # travessões: utf8 nativo
    assert not odd, f"caracteres sem suporte no pdflatex: {odd}"
    out = OUT / "main.tex"
    out.write_text(text, encoding="utf-8")
    return out


if __name__ == "__main__":
    print(build())
