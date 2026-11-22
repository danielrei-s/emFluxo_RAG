"""Recuperação: fusão RRF, pesquisa híbrida, rerank e seleção (F4)."""

from rag_core.retrieval.fusion import rrf_fuse
from rag_core.retrieval.hybrid import HybridRetriever
from rag_core.retrieval.rerank import NoopReranker
from rag_core.retrieval.selection import select_context

__all__ = ["HybridRetriever", "NoopReranker", "rrf_fuse", "select_context"]
