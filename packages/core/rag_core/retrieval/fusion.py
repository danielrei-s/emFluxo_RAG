"""Reciprocal Rank Fusion (F4-T01)."""

from __future__ import annotations

from collections.abc import Sequence

from rag_core.types import SearchHit


def rrf_fuse(
    rankings: Sequence[Sequence[SearchHit]], *, k: int = 60, limit: int
) -> list[SearchHit]:
    """Funde listas ordenadas: ``score = Σ 1/(k + posição)`` (posição desde 1).

    Deduplica por ``chunk_id`` (uma lista só conta uma vez cada chunk) e desempata por
    ``chunk_id``; os resultados têm ``stage="fused"``.
    """
    scores: dict[str, float] = {}
    hits: dict[str, SearchHit] = {}
    for ranking in rankings:
        seen: set[str] = set()
        position = 0
        for hit in ranking:
            chunk_id = hit.chunk.chunk_id
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            position += 1
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + position)
            hits.setdefault(chunk_id, hit)
    ordered = sorted(scores, key=lambda cid: (-scores[cid], cid))
    return [
        hits[cid].model_copy(update={"score": scores[cid], "stage": "fused"})
        for cid in ordered[:limit]
    ]
