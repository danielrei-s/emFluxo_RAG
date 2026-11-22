"""A suite de contrato do VectorStore aplicada ao ``SqliteVectorStore`` (FTS5 e fallback)."""

from __future__ import annotations

import sqlite3

from rag_core.fakes import FakeEmbedder
from rag_core.interfaces import VectorStore
from rag_core.stores import SqliteVectorStore

from ..contract.vectorstore_contract import VectorStoreContract

DIM = FakeEmbedder().dim


def _memory_connection() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


class TestSqliteContractFts5(VectorStoreContract):
    supports_local_origin = True

    def make_store(self) -> VectorStore:
        store = SqliteVectorStore(_memory_connection, DIM, keyword_backend="fts5")
        assert store.keyword_backend == "fts5"
        return store


class TestSqliteContractMemoryFallback(VectorStoreContract):
    supports_local_origin = True

    def make_store(self) -> VectorStore:
        store = SqliteVectorStore(_memory_connection, DIM, keyword_backend="memory")
        assert store.keyword_backend == "memory"
        return store
