"""Cliente da API do Claude (SDK oficial ``anthropic``).

Cada chamada é independente (sem histórico multi-turno na API): o contexto do
agente vem da sua própria memória (``Knowledge``), sintetizada no prompt.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from llm_mas.llm.base import BudgetExceeded, LLMError, LLMRefusal

DEFAULT_MODEL = "claude-opus-5-5"

# US$ por milhão de tokens (entrada, saída) — usados só para a estimativa de custo
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-1": (10.0, 50.0),
}


__all__ = ["BudgetExceeded", "ClaudeLLM", "DEFAULT_MODEL", "PRICES"]


class ClaudeLLM:
    """Implementa ``LLMClient`` sobre o Messages API.

    * ``effort`` controla a profundidade do raciocínio (o pensamento adaptativo
      é sempre ativo neste modelo). ``"low"`` reduz custo e latência quando há
      muitos agentes chamando o modelo a cada iteração.
    * ``use_fallbacks`` habilita o *fallback* no servidor: se o modelo recusar
      uma solicitação, a API a reexecuta em outro modelo na mesma chamada.
    * ``max_cost`` (US$) interrompe a execução com ``BudgetExceeded`` quando o
      custo estimado acumulado atinge o limite.
    * ``transcript`` grava cada chamada (prompt, resposta, uso) em JSONL, para
      que os experimentos possam ser auditados e reproduzidos.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        effort: str = "medium",
        max_tokens: int = 16000,
        use_fallbacks: bool = True,
        client: Any = None,
        max_cost: float | None = None,
        transcript: str | Path | None = None,
    ) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise LLMError("instale o SDK: pip install 'llm-mas[llm]'") from exc
        self._anthropic = anthropic
        self._client = client or anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.use_fallbacks = use_fallbacks
        self.max_cost = max_cost
        self.transcript = Path(transcript) if transcript else None
        self.tag = ""  # rótulo gravado no transcript (ex.: "icu/seed0/adaptive-llm")
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self._lock = threading.Lock()

    @property
    def cost(self) -> float:
        price_in, price_out = PRICES.get(self.model, PRICES[DEFAULT_MODEL])
        return (self.input_tokens * price_in + self.output_tokens * price_out) / 1_000_000

    def usage(self) -> dict[str, Any]:
        return {"model": self.model, "effort": self.effort, "calls": self.calls,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "estimated_cost_usd": round(self.cost, 4)}

    def generate(self, system: str, prompt: str) -> str:
        return self._create(system, prompt, {"effort": self.effort})

    def generate_json(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        text = self._create(
            system,
            prompt,
            {"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
        )
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"resposta não é JSON válido: {text[:200]}") from exc

    def _create(self, system: str, prompt: str, output_config: dict[str, Any]) -> str:
        anthropic = self._anthropic
        if self.max_cost is not None and self.cost >= self.max_cost:
            raise BudgetExceeded(f"custo estimado US$ {self.cost:.2f} atingiu o limite de US$ {self.max_cost:.2f}")
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": output_config,
        }
        try:
            if self.use_fallbacks:
                response = self._client.beta.messages.create(
                    **kwargs,
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                )
            else:
                response = self._client.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise LLMError("credenciais inválidas: defina ANTHROPIC_API_KEY ou use `ant auth login`") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("limite de requisições atingido; tente novamente mais tarde") from exc
        except anthropic.APIStatusError as exc:
            if "credit balance is too low" in str(exc.message):
                raise BudgetExceeded("créditos da API esgotados (Plans & Billing no Console)") from exc
            raise LLMError(f"erro da API ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("falha de conexão com a API") from exc

        text = "".join(block.text for block in response.content if block.type == "text")
        with self._lock:
            self.calls += 1
            self.input_tokens += response.usage.input_tokens
            self.output_tokens += response.usage.output_tokens
            if self.transcript:
                with self.transcript.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "tag": self.tag, "model": response.model, "stop_reason": response.stop_reason,
                        "input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens,
                        "system": system, "prompt": prompt, "output": text,
                    }, ensure_ascii=False) + "\n")

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise LLMRefusal(getattr(details, "category", None), getattr(details, "explanation", None))
        if response.stop_reason == "max_tokens":
            raise LLMError("resposta truncada por max_tokens")
        return text
