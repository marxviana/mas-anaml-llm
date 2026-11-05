r"""Tradução da saída do LLM em ações (etapa *Execute*).

Usa a convenção do artigo arXiv:2307.06187::

    \begin{action}Agent4: Buy_Book: 18\end{action}

O ``\`` inicial é opcional, pois os registros do artigo mostram o modelo
omitindo-o (``begin{action}``).
"""

from __future__ import annotations

import re

from llm_mas.core.messages import Action

ACTION_RE = re.compile(
    r"\\?begin\{action\}\s*([\w.\-]+)\s*:\s*(.*?)\s*\\?end\{action\}",
    re.DOTALL,
)

ACTION_FORMAT_HELP = (
    "Para enviar uma mensagem a um agente, escreva exatamente:\n"
    "\\begin{action}<IdDoAgente>: <mensagem>\\end{action}\n"
    "Você pode emitir zero ou mais ações. Texto fora desse formato é ignorado."
)


def parse_actions(text: str, sender: str) -> list[Action]:
    return [Action.send(sender, receiver, content) for receiver, content in ACTION_RE.findall(text)]


def format_action(receiver: str, content: str) -> str:
    return f"\\begin{{action}}{receiver}: {content}\\end{{action}}"
