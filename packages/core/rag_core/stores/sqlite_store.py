"""``VectorStore`` persistente em SQLite (F5-T01): FTS5 + pesquisa vetorial em memória."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from typing import Any, Literal

import numpy as np

from rag_core.errors import ValidationFailed
from rag_core.policy import can_read
from rag_core.stores.keyword_index import Bm25MemoryIndex, Fts5KeywordIndex, KeywordIndex
from rag_core.types import (
    AccessFilter,
    Acl,
    Chunk,
    ChunkMetadata,
    Classification,
    SearchHit,
)

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS chunks (
        chunk_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        doc_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        text TEXT NOT NULL,
        meta_json TEXT NOT NULL,
        embedding BLOB,
        embedding_model TEXT,
        doc_hash TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_chunks_tenant_doc ON chunks(tenant_id, doc_id)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_tenant_workspace ON chunks(tenant_id, workspace_id)",
)
_BATCH = 400  # abaixo do limite de variáveis do SQLite


def _batches(items: Sequence[str], size: int = _BATCH) -> Iterator[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class SqliteVectorStore:
    """Chunks, metadados e vetores float32 num ficheiro SQLite.

    Toda a leitura passa por ``policy.can_read`` (INV-02). A pesquisa vetorial usa uma matriz
    numpy por tenant, em cache e invalidada por cada escrita (a própria ou de outra ligação).
    """

    def __init__(
        self,
        conn_factory: Callable[[], sqlite3.Connection],
        dim: int,
        *,
        keyword_backend: Literal["auto", "fts5", "memory"] = "auto",
    ) -> None:
        if dim < 1:
            raise ValueError("dim tem de ser positivo")
        self._conn = conn_factory()
        self.dim = dim
        self._backend_choice = keyword_backend
        self._keywords: KeywordIndex
        self._version = 0
        self._matrices: dict[str, tuple[tuple[int, int], list[str], np.ndarray]] = {}
        self.matrix_builds = 0  # quantas vezes uma matriz foi reconstruída (testes)
        self.init()

    # ------------------------------------------------------------------ esquema

    def init(self) -> None:
        """Cria o esquema (idempotente) e escolhe o índice lexical."""
        with self._conn:
            for statement in _SCHEMA:
                self._conn.execute(statement)
        self._keywords = self._make_keyword_index()

    def _make_keyword_index(self) -> KeywordIndex:
        if self._backend_choice != "memory":
            try:
                with self._conn:
                    return Fts5KeywordIndex.create(self._conn)
            except sqlite3.OperationalError:
                if self._backend_choice == "fts5":
                    raise
        index = Bm25MemoryIndex()
        for chunk_id, tenant_id, text in self._conn.execute(
            "SELECT chunk_id, tenant_id, text FROM chunks"
        ):
            index.add(chunk_id, tenant_id, text)
        return index

    @property
    def keyword_backend(self) -> str:
        return "fts5" if isinstance(self._keywords, Fts5KeywordIndex) else "memory"

    def close(self) -> None:
        self._conn.close()

    # --------------------------------------------------------------- conversões

    def _row_to_chunk(self, row: tuple[Any, ...]) -> Chunk:
        chunk_id, ordinal, text, meta_json, blob, model = row
        embedding = None
        if blob is not None:
            embedding = tuple(float(x) for x in np.frombuffer(bytes(blob), dtype="<f4"))
        return Chunk(
            chunk_id=str(chunk_id),
            ordinal=int(ordinal),
            text=str(text),
            metadata=ChunkMetadata.model_validate_json(str(meta_json)),
            embedding=embedding,
            embedding_model=None if model is None else str(model),
        )

    _CHUNK_COLUMNS = "chunk_id, ordinal, text, meta_json, embedding, embedding_model"

    def _fetch(self, chunk_ids: Sequence[str]) -> dict[str, Chunk]:
        found: dict[str, Chunk] = {}
        for batch in _batches(list(chunk_ids)):
            marks = ",".join("?" * len(batch))
            rows = self._conn.execute(
                f"SELECT {self._CHUNK_COLUMNS} FROM chunks WHERE chunk_id IN ({marks})", batch
            ).fetchall()
            for row in rows:
                chunk = self._row_to_chunk(row)
                found[chunk.chunk_id] = chunk
        return found

    # ------------------------------------------------------------------ escrita

    def upsert(self, chunks: Sequence[Chunk]) -> None:
        """Insere ou substitui chunks, de forma atómica."""
        for chunk in chunks:
            if chunk.embedding is not None and len(chunk.embedding) != self.dim:
                raise ValidationFailed(subcode="embedding_dimension_mismatch")
        with self._conn:  # tudo ou nada
            self._keywords.remove([c.chunk_id for c in chunks])
            for chunk in chunks:
                meta = chunk.metadata
                blob = (
                    None
                    if chunk.embedding is None
                    else np.asarray(chunk.embedding, dtype="<f4").tobytes()
                )
                self._conn.execute(
                    "INSERT OR REPLACE INTO chunks(chunk_id, tenant_id, workspace_id, doc_id, "
                    "ordinal, text, meta_json, embedding, embedding_model, doc_hash) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        chunk.chunk_id,
                        meta.tenant_id,
                        meta.workspace_id,
                        meta.doc_id,
                        chunk.ordinal,
                        chunk.text,
                        meta.model_dump_json(),
                        blob,
                        chunk.embedding_model,
                        meta.doc_hash,
                    ),
                )
                self._keywords.add(chunk.chunk_id, meta.tenant_id, chunk.text)
        self._version += 1

    def delete_document(self, tenant_id: str, doc_id: str) -> int:
        with self._conn:
            ids = [
                row[0]
                for row in self._conn.execute(
                    "SELECT chunk_id FROM chunks WHERE tenant_id = ? AND doc_id = ?",
                    (tenant_id, doc_id),
                )
            ]
            self._keywords.remove(ids)
            self._conn.execute(
                "DELETE FROM chunks WHERE tenant_id = ? AND doc_id = ?", (tenant_id, doc_id)
            )
        self._version += 1
        return len(ids)

    def update_acl(
        self, tenant_id: str, doc_id: str, acl: Acl, classification: Classification
    ) -> int:
        with self._conn:
            rows = self._conn.execute(
                "SELECT chunk_id, meta_json FROM chunks WHERE tenant_id = ? AND doc_id = ?",
                (tenant_id, doc_id),
            ).fetchall()
            for chunk_id, meta_json in rows:
                meta = ChunkMetadata.model_validate_json(meta_json)
                updated = meta.model_copy(update={"acl": acl, "classification": classification})
                self._conn.execute(
                    "UPDATE chunks SET meta_json = ? WHERE chunk_id = ?",
                    (updated.model_dump_json(), chunk_id),
                )
        return len(rows)

    def document_hashes(self, tenant_id: str, workspace_id: str) -> dict[str, str]:
        rows = self._conn.execute(
            "SELECT doc_id, doc_hash FROM chunks WHERE tenant_id = ? AND workspace_id = ?",
            (tenant_id, workspace_id),
        )
        return {str(doc_id): str(doc_hash) for doc_id, doc_hash in rows}

    # ------------------------------------------------------------------ leitura

    def get_chunks(self, chunk_ids: Sequence[str], *, flt: AccessFilter) -> list[Chunk]:
        found = self._fetch(chunk_ids)
        return [
            found[cid] for cid in chunk_ids if cid in found and can_read(flt, found[cid].metadata)
        ]

    def _readable(self, ranked_ids: Sequence[str], flt: AccessFilter, k: int) -> list[str]:
        """Do topo da lista, os primeiros ``k`` que o filtro pode ler (metadados em lotes)."""
        readable: list[str] = []
        for batch in _batches(list(ranked_ids)):
            marks = ",".join("?" * len(batch))
            rows = dict(
                self._conn.execute(
                    f"SELECT chunk_id, meta_json FROM chunks WHERE chunk_id IN ({marks})", batch
                ).fetchall()
            )
            for chunk_id in batch:
                meta_json = rows.get(chunk_id)
                if meta_json is not None and can_read(
                    flt, ChunkMetadata.model_validate_json(meta_json)
                ):
                    readable.append(chunk_id)
                    if len(readable) == k:
                        return readable
        return readable

    def _matrix(self, tenant_id: str) -> tuple[list[str], np.ndarray]:
        key = (self._version, int(self._conn.execute("PRAGMA data_version").fetchone()[0]))
        cached = self._matrices.get(tenant_id)
        if cached is not None and cached[0] == key:
            return cached[1], cached[2]
        rows = self._conn.execute(
            "SELECT chunk_id, embedding FROM chunks "
            "WHERE tenant_id = ? AND embedding IS NOT NULL ORDER BY chunk_id",
            (tenant_id,),
        ).fetchall()
        ids = [str(chunk_id) for chunk_id, _ in rows]
        matrix = (
            np.vstack([np.frombuffer(bytes(blob), dtype="<f4") for _, blob in rows])
            if rows
            else np.zeros((0, self.dim), dtype="<f4")
        ).astype(np.float64)
        norms = np.linalg.norm(matrix, axis=1)
        matrix = np.divide(
            matrix, norms[:, None], out=np.zeros_like(matrix), where=norms[:, None] > 0
        )
        self._matrices[tenant_id] = (key, ids, matrix)
        self.matrix_builds += 1
        return ids, matrix

    def search_vector(
        self, embedding: Sequence[float], *, flt: AccessFilter, k: int
    ) -> list[SearchHit]:
        ids, matrix = self._matrix(flt.tenant_id)
        if not ids:
            return []
        query = np.asarray(embedding, dtype=np.float64)
        norm = float(np.linalg.norm(query))
        scores = matrix @ (query / norm) if norm > 0 else np.zeros(len(ids))
        order = np.lexsort((np.asarray(ids), -scores))  # melhor primeiro; empates por chunk_id
        ranked = [ids[i] for i in order]
        score_of = dict(zip(ids, scores.tolist(), strict=True))
        chosen = self._readable(ranked, flt, k)
        chunks = self._fetch(chosen)
        return [
            SearchHit(chunk=chunks[cid], score=float(score_of[cid]), stage="vector")
            for cid in chosen
        ]

    def search_keyword(self, query: str, *, flt: AccessFilter, k: int) -> list[SearchHit]:
        limit = max(k * 4, 16)
        while True:
            candidates = self._keywords.search(query, flt.tenant_id, limit)
            chosen = self._readable([cid for cid, _ in candidates], flt, k)
            if len(chosen) == k or len(candidates) < limit:
                break
            limit *= 4  # os candidatos de topo eram ilegíveis: procura mais fundo
        score_of = dict(candidates)
        chunks = self._fetch(chosen)
        return [
            SearchHit(chunk=chunks[cid], score=float(score_of[cid]), stage="keyword")
            for cid in chosen
        ]
