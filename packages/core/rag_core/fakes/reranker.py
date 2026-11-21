"""Reranker falso: similaridade de Jaccard entre tokens, com desempate determinístico."""

from __future__ import annotations

from collections.abc import Sequence

from rag_core.text import normalize_tokens
from rag_core.types import SearchHit


class FakeReranker:
    """Ordena por Jaccard; desempata pelo score anterior e depois por ``chunk_id``."""

    model_id = "fake-jaccard"

    def rerank(self, query: str, hits: Sequence[SearchHit], *, top_n: int) -> list[SearchHit]:
        query_tokens = set(normalize_tokens(query))
        scored: list[tuple[float, SearchHit]] = []
        for hit in hits:
            chunk_tokens = set(normalize_tokens(hit.chunk.text))
            union = query_tokens | chunk_tokens
            jaccard = len(query_tokens & chunk_tokens) / len(union) if union else 0.0
            scored.append((jaccard, hit))
        scored.sort(key=lambda item: (-item[0], -item[1].score, item[1].chunk.chunk_id))
        return [
            SearchHit(chunk=hit.chunk, score=score, stage="reranked")
            for score, hit in scored[:top_n]
        ]
