"""LLM adapters. Design rule: code measures, the model only interprets text/JSON."""

from __future__ import annotations

from marked import config
from marked.llm.base import LLM, NullLLM

_instance: LLM | None = None


def get_llm() -> LLM:
    global _instance
    if _instance is None:
        if config.LLM_MODE == "fake":
            from marked.llm.fake_llm import FakeLLM
            _instance = FakeLLM()
        elif config.ANTHROPIC_API_KEY:
            from marked.llm.anthropic_llm import AnthropicLLM
            _instance = AnthropicLLM(model=config.ANTHROPIC_MODEL)
        else:
            _instance = NullLLM()
    return _instance


def set_llm(llm: LLM | None) -> None:
    """Test hook."""
    global _instance
    _instance = llm


def llm_status() -> dict:
    llm = get_llm()
    return {"available": llm.available, "provider": llm.name, "model": getattr(llm, "model", None),
            "reason": None if llm.available else "No ANTHROPIC_API_KEY set. Set it and restart to enable Suggest marks, coaching, Improvise content review and LLM-checked definitions."}
