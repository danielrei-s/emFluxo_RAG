"""``VectorStore`` em memória: referência de comportamento para os stores reais."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from rank_bm25 import BM25Plus

from rag_core.policy import can_read
from rag_core.text import normalize_tokens
from rag_core.types import AccessFilter, Acl, Chunk, Classification, SearchHit


class InMemoryVectorStore:
    """Guarda chunks num dicionário; toda a leitura passa por ``policy.can_read`` (INV-02)."""

    def __init__(self) -> None:
        self._chunks: dict[str, Chunk] = {}

    def upsert(self, chunks: Sequence[Chunk]) -> None:
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk

    def delete_document(self, tenant_id: str, doc_id: str) -> int:
        doomed = [
            cid
            for cid, c in self._chunks.items()
            if c.metadata.tenant_id == tenant_id and c.metadata.doc_id == doc_id
        ]
        for cid in doomed:
            del self._chunks[cid]
        return len(doomed)

    def document_hashes(self, tenant_id: str, workspace_id: str) -> dict[str, str]:
        return {
            c.metadata.doc_id: c.metadata.doc_hash
            for c in self._chunks.values()
            if c.metadata.tenant_id == tenant_id and c.metadata.workspace_id == workspace_id
        }

    def update_acl(
        self, tenant_id: str, doc_id: str, acl: Acl, classification: Classification
    ) -> int:
        updated = 0
        for cid, chunk in list(self._chunks.items()):
            meta = chunk.metadata
            if meta.tenant_id == tenant_id and meta.doc_id == doc_id:
                new_meta = meta.model_copy(update={"acl": acl, "classification": classification})
                self._chunks[cid] = chunk.model_copy(update={"metadata": new_meta})
                updated += 1
        return updated

    def _readable(self, flt: AccessFilter) -> list[Chunk]:
        return [c for c in self._chunks.values() if can_read(flt, c.metadata)]

    def search_vector(
        self, embedding: Sequence[float], *, flt: AccessFilter, k: int
    ) -> list[SearchHit]:
        query = np.asarray(embedding, dtype=float)
        query_norm = float(np.linalg.norm(query))
        scored: list[tuple[float, Chunk]] = []
        for chunk in self._readable(flt):
            if chunk.embedding is None:
                continue
            vec = np.asarray(chunk.embedding, dtype=float)
            denom = query_norm * float(np.linalg.norm(vec))
            score = float(np.dot(query, vec) / denom) if denom else 0.0
            scored.append((score, chunk))
        scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
        return [SearchHit(chunk=c, score=s, stage="vector") for s, c in scored[:k]]

    def search_keyword(self, query: str, *, flt: AccessFilter, k: int) -> list[SearchHit]:
        query_tokens = normalize_tokens(query)
        candidates = self._readable(flt)
        if not query_tokens or not candidates:
            return []
        corpus = [normalize_tokens(c.text) or ["_"] for c in candidates]
        scores = BM25Plus(corpus).get_scores(query_tokens)
        wanted = set(query_tokens)
        # BM25Plus dá score positivo a documentos sem nenhum termo: exigimos uma correspondência.
        scored = [
            (float(s), c)
            for s, c, tokens in zip(scores, candidates, corpus, strict=True)
            if s > 0 and wanted.intersection(tokens)
        ]
        scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
        return [SearchHit(chunk=c, score=s, stage="keyword") for s, c in scored[:k]]

    def get_chunks(self, chunk_ids: Sequence[str], *, flt: AccessFilter) -> list[Chunk]:
        found: list[Chunk] = []
        for chunk_id in chunk_ids:
            chunk = self._chunks.get(chunk_id)
            if chunk is not None and can_read(flt, chunk.metadata):
                found.append(chunk)
        return found
