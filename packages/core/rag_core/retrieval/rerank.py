"""Rerankers sem modelo (F4-T02)."""

from __future__ import annotations

from collections.abc import Sequence

from rag_core.types import SearchHit


class NoopReranker:
    """Mantém a ordem recebida (útil quando não há modelo de rerank)."""

    model_id = "noop"

    def rerank(self, query: str, hits: Sequence[SearchHit], *, top_n: int) -> list[SearchHit]:
        return [hit.model_copy(update={"stage": "reranked"}) for hit in hits[:top_n]]
