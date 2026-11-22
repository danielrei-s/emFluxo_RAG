"""Seleção do contexto final: rerank, limiar de relevância e limite por documento (F4-T02)."""

from __future__ import annotations

from collections.abc import Sequence

from rag_core.config import Settings
from rag_core.interfaces import Reranker
from rag_core.types import SearchHit


def select_context(
    query: str, hits: Sequence[SearchHit], *, reranker: Reranker, settings: Settings
) -> list[SearchHit]:
    """Escolhe até ``top_n`` excertos relevantes, no máximo ``max_chunks_per_doc`` por documento.

    Com ``rerank_enabled`` os scores do reranker (0 a 1) têm de atingir ``min_relevance``; sem
    rerank usa-se a ordem da fusão, sem limiar (os scores RRF não são comparáveis a 0-1).
    """
    cfg = settings.retrieval
    if cfg.rerank_enabled:
        ranked = [
            h
            for h in reranker.rerank(query, hits, top_n=cfg.top_n * 2)
            if h.score >= cfg.min_relevance
        ]
    else:
        ranked = list(hits)
    selected: list[SearchHit] = []
    per_doc: dict[str, int] = {}
    for hit in ranked:
        doc_id = hit.chunk.metadata.doc_id
        if per_doc.get(doc_id, 0) >= cfg.max_chunks_per_doc:
            continue
        per_doc[doc_id] = per_doc.get(doc_id, 0) + 1
        selected.append(hit)
        if len(selected) == cfg.top_n:
            break
    return selected
