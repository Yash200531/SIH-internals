"""Bounded clinical language-model orchestration.

The default provider is deterministic and local. No model is downloaded and no
patient data leaves the API process while ``LLM_PROVIDER=mock``.
"""

from app.llm.service import LLMRouter, get_llm_router

__all__ = ["LLMRouter", "get_llm_router"]
