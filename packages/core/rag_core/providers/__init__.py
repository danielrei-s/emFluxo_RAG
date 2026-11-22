"""Adaptadores de modelos reais (F5-T02)."""

from rag_core.providers.model_registry import ModelRegistry, ModelSpec
from rag_core.providers.openai_compat import OpenAICompatibleEmbedder, OpenAICompatibleLLM

__all__ = ["ModelRegistry", "ModelSpec", "OpenAICompatibleEmbedder", "OpenAICompatibleLLM"]
