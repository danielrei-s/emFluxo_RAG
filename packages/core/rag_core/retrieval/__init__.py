"""Recuperação: fusão RRF, pesquisa híbrida, rerank e seleção (F4)."""

from rag_core.retrieval.fusion import rrf_fuse
from rag_core.retrieval.hybrid import HybridRetriever

__all__ = ["HybridRetriever", "rrf_fuse"]
