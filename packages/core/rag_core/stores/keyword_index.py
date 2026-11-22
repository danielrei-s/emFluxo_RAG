"""Índices lexicais do store SQLite (F5-T01): FTS5 e o fallback BM25 em memória."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from typing import Protocol

from rank_bm25 import BM25Plus

from rag_core.text import normalize_tokens


class KeywordIndex(Protocol):
    """Índice lexical por tenant. As escritas ficam na transação do store (sem commit próprio)."""

    def add(self, chunk_id: str, tenant_id: str, text: str) -> None: ...

    def remove(self, chunk_ids: Sequence[str]) -> None: ...

    def search(self, query: str, tenant_id: str, limit: int) -> list[tuple[str, float]]:
        """``(chunk_id, score)`` com o melhor primeiro; só chunks com algum termo da pergunta."""
        ...


class Fts5KeywordIndex:
    """FTS5 com ``unicode61 remove_diacritics 2``; pergunta = tokens entre aspas unidos por OR."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def create(cls, conn: sqlite3.Connection) -> Fts5KeywordIndex:
        """Cria a tabela virtual; levanta ``sqlite3.OperationalError`` se não houver FTS5."""
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
            "chunk_id UNINDEXED, tenant_id UNINDEXED, text, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
        return cls(conn)

    def add(self, chunk_id: str, tenant_id: str, text: str) -> None:
        self._conn.execute(
            "INSERT INTO chunks_fts(chunk_id, tenant_id, text) VALUES (?, ?, ?)",
            (chunk_id, tenant_id, text),
        )

    def remove(self, chunk_ids: Sequence[str]) -> None:
        self._conn.executemany(
            "DELETE FROM chunks_fts WHERE chunk_id = ?", [(cid,) for cid in chunk_ids]
        )

    def search(self, query: str, tenant_id: str, limit: int) -> list[tuple[str, float]]:
        tokens = normalize_tokens(query)
        if not tokens:
            return []
        match = " OR ".join(f'"{token}"' for token in dict.fromkeys(tokens))
        rows = self._conn.execute(
            "SELECT chunk_id, bm25(chunks_fts) AS rank FROM chunks_fts "
            "WHERE chunks_fts MATCH ? AND tenant_id = ? ORDER BY rank, chunk_id LIMIT ?",
            (match, tenant_id, limit),
        ).fetchall()
        return [(str(chunk_id), -float(rank)) for chunk_id, rank in rows]  # bm25() é negativo


class Bm25MemoryIndex:
    """Fallback sem FTS5: BM25 em memória (``rank-bm25``), reconstruído após cada escrita."""

    def __init__(self) -> None:
        self._docs: dict[str, tuple[str, list[str]]] = {}
        self._cache: dict[str, tuple[list[str], BM25Plus]] = {}

    def add(self, chunk_id: str, tenant_id: str, text: str) -> None:
        self._docs[chunk_id] = (tenant_id, normalize_tokens(text))
        self._cache.pop(tenant_id, None)

    def remove(self, chunk_ids: Sequence[str]) -> None:
        for chunk_id in chunk_ids:
            removed = self._docs.pop(chunk_id, None)
            if removed is not None:
                self._cache.pop(removed[0], None)

    def _index(self, tenant_id: str) -> tuple[list[str], BM25Plus] | None:
        if tenant_id not in self._cache:
            ids = sorted(cid for cid, (tenant, _) in self._docs.items() if tenant == tenant_id)
            if not ids:
                return None
            corpus = [self._docs[cid][1] or ["_"] for cid in ids]
            self._cache[tenant_id] = (ids, BM25Plus(corpus))
        return self._cache[tenant_id]

    def search(self, query: str, tenant_id: str, limit: int) -> list[tuple[str, float]]:
        tokens = normalize_tokens(query)
        index = self._index(tenant_id)
        if not tokens or index is None:
            return []
        ids, bm25 = index
        wanted = set(tokens)
        scores = bm25.get_scores(tokens)
        scored = [
            (cid, float(score))
            for cid, score in zip(ids, scores, strict=True)
            if score > 0 and wanted.intersection(self._docs[cid][1])
        ]
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored[:limit]
