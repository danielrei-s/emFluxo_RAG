"""Recuperação híbrida: pesquisa vetorial + lexical, fundidas por RRF (F4-T01)."""

from __future__ import annotations

from rag_core.config import Settings
from rag_core.interfaces import Embedder, VectorStore
from rag_core.retrieval.fusion import rrf_fuse
from rag_core.types import AccessFilter, SearchHit

INJECTION_FLAG = "suspected_injection"


class HybridRetriever:
    """Combina ``search_vector`` e ``search_keyword`` (ambas com o mesmo ``AccessFilter``)."""

    def __init__(self, store: VectorStore, embedder: Embedder, settings: Settings) -> None:
        self._store = store
        self._embedder = embedder
        self._cfg = settings.retrieval

    def retrieve(self, query: str, flt: AccessFilter) -> list[SearchHit]:
        """Os melhores ``rerank_top_in`` resultados; chunks suspeitos são penalizados."""
        cfg = self._cfg
        vector = self._store.search_vector(
            self._embedder.embed_query(query), flt=flt, k=cfg.k_vector
        )
        keyword = self._store.search_keyword(query, flt=flt, k=cfg.k_keyword)
        fused = rrf_fuse([vector, keyword], k=cfg.rrf_k, limit=cfg.k_vector + cfg.k_keyword)
        adjusted = [
            hit.model_copy(update={"score": hit.score * cfg.injection_downweight})
            if INJECTION_FLAG in hit.chunk.metadata.flags
            else hit
            for hit in fused
        ]
        adjusted.sort(key=lambda h: (-h.score, h.chunk.chunk_id))
        return adjusted[: cfg.rerank_top_in]
