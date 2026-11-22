"""Geração: prompt, validação de citações, filtro de saída e conversa (F4)."""

from rag_core.generation.constants import GENERAL_KNOWLEDGE_MARKER, NOT_FOUND
from rag_core.generation.prompt_builder import PromptBundle, build_messages

__all__ = ["GENERAL_KNOWLEDGE_MARKER", "NOT_FOUND", "PromptBundle", "build_messages"]
