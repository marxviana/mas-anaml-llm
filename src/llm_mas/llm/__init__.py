from llm_mas.llm.base import FunctionLLM, LLMClient, LLMError, LLMRefusal
from llm_mas.llm.parsing import parse_actions

__all__ = ["FunctionLLM", "LLMClient", "LLMError", "LLMRefusal", "parse_actions", "make_llm"]


def make_llm(kind: str, **kwargs) -> LLMClient | None:
    """``"offline"`` → ``None`` (agentes usam políticas heurísticas);
    ``"claude"`` → cliente da API do Claude."""
    if kind == "offline":
        return None
    if kind == "claude":
        from llm_mas.llm.claude import ClaudeLLM

        return ClaudeLLM(**kwargs)
    raise ValueError(f"LLM desconhecido: {kind!r} (use 'offline' ou 'claude')")
