"""Testes de F5-T01: ``SqliteVectorStore`` (persistência, vetores, FTS5, fallback e cache)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from rag_core.errors import ValidationFailed
from rag_core.fakes import FakeEmbedder
from rag_core.stores import Bm25MemoryIndex, SqliteVectorStore
from rag_core.testing.chunks import make_chunk
from rag_core.types import AccessFilter, Acl, Classification, Role

EMBEDDER = FakeEmbedder()
DIM = EMBEDDER.dim
FLT = AccessFilter(tenant_id="t1", user_id="u1", role=Role.MEMBER, groups=frozenset({"g1"}))


def _mem() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


def _file_factory(path: Path) -> Callable[[], sqlite3.Connection]:
    return lambda: sqlite3.connect(path)


class _NoFts5:
    """Ligação que recusa FTS5, como um SQLite compilado sem a extensão."""

    def __init__(self) -> None:
        self._conn = sqlite3.connect(":memory:")

    def execute(self, sql: str, *args: Any) -> sqlite3.Cursor:
        if "fts5" in sql.lower():
            raise sqlite3.OperationalError("no such module: fts5")
        return self._conn.execute(sql, *args)

    def executemany(self, sql: str, *args: Any) -> sqlite3.Cursor:
        return self._conn.executemany(sql, *args)

    def __enter__(self) -> sqlite3.Connection:
        return self._conn.__enter__()

    def __exit__(self, *exc: Any) -> Any:
        return self._conn.__exit__(*exc)

    def close(self) -> None:
        self._conn.close()


def _texts(hits: list[Any]) -> list[str]:
    return [h.chunk.text for h in hits]


def test_persistence_across_connections(tmp_path: Path) -> None:
    path = tmp_path / "chunks.db"
    chunk = make_chunk("Relatório anual de vendas", doc_id="d1")
    first = SqliteVectorStore(_file_factory(path), DIM)
    first.upsert([chunk])
    first.close()

    second = SqliteVectorStore(_file_factory(path), DIM)
    assert second.document_hashes("t1", "w1") == {"d1": chunk.metadata.doc_hash}
    assert [c.chunk_id for c in second.get_chunks([chunk.chunk_id], flt=FLT)] == [chunk.chunk_id]
    assert _texts(second.search_keyword("vendas", flt=FLT, k=5)) == ["Relatório anual de vendas"]
    assert len(second.search_vector(EMBEDDER.embed_query("vendas"), flt=FLT, k=5)) == 1
    second.close()


def test_embedding_roundtrip_float32() -> None:
    chunk = make_chunk("texto com vetor", doc_id="d1")
    store = SqliteVectorStore(_mem, DIM)
    store.upsert([chunk])
    (stored,) = store.get_chunks([chunk.chunk_id], flt=FLT)
    assert chunk.embedding is not None and stored.embedding is not None
    expected = tuple(float(np.float32(x)) for x in chunk.embedding)
    assert stored.embedding == expected
    assert stored.embedding_model == chunk.embedding_model
    assert len(stored.embedding) == DIM
    no_vector = make_chunk("sem vetor", doc_id="d2", embed=False)
    store.upsert([no_vector])
    (plain,) = store.get_chunks([no_vector.chunk_id], flt=FLT)
    assert plain.embedding is None and plain.embedding_model is None


def test_fts_accent_insensitive() -> None:
    store = SqliteVectorStore(_mem, DIM)
    if store.keyword_backend != "fts5":
        pytest.skip("este SQLite não tem FTS5")
    store.upsert([make_chunk("O orçamento de 2026 foi aprovado", doc_id="a")])
    assert _texts(store.search_keyword("orcamento", flt=FLT, k=5)) == [
        "O orçamento de 2026 foi aprovado"
    ]
    assert len(store.search_keyword("ORÇAMENTO aprovação", flt=FLT, k=5)) == 1  # OR de termos
    hit = store.search_keyword("orçamento", flt=FLT, k=5)[0]
    assert hit.stage == "keyword" and hit.score > 0
    assert store.search_keyword("   ", flt=FLT, k=5) == []
    assert store.search_keyword("inexistente", flt=FLT, k=5) == []


def test_fallback_keyword_index_when_fts5_missing() -> None:
    store = SqliteVectorStore(_NoFts5, DIM)  # type: ignore[arg-type]
    assert store.keyword_backend == "memory"
    store.upsert(
        [
            make_chunk("O orçamento de 2026 foi aprovado", doc_id="a"),
            make_chunk("A reunião é na quinta-feira", doc_id="b"),
        ]
    )
    assert _texts(store.search_keyword("orcamento", flt=FLT, k=5)) == [
        "O orçamento de 2026 foi aprovado"
    ]
    assert _texts(store.search_keyword("REUNIAO", flt=FLT, k=5)) == ["A reunião é na quinta-feira"]
    store.delete_document("t1", "a")
    assert store.search_keyword("orcamento", flt=FLT, k=5) == []
    with pytest.raises(sqlite3.OperationalError):  # exigir FTS5 sem o ter falha claramente
        SqliteVectorStore(_NoFts5, DIM, keyword_backend="fts5")  # type: ignore[arg-type]


def test_memory_index_is_rebuilt_from_the_database_on_reopen(tmp_path: Path) -> None:
    path = tmp_path / "chunks.db"
    SqliteVectorStore(_file_factory(path), DIM).upsert(
        [make_chunk("plano de contingência", doc_id="d")]
    )
    reopened = SqliteVectorStore(_file_factory(path), DIM, keyword_backend="memory")
    assert _texts(reopened.search_keyword("contingencia", flt=FLT, k=3)) == [
        "plano de contingência"
    ]


def test_cache_invalidated_after_write(tmp_path: Path) -> None:
    store = SqliteVectorStore(_mem, DIM)
    store.upsert([make_chunk("primeiro documento", doc_id="a")])
    query = EMBEDDER.embed_query("primeiro documento")
    assert len(store.search_vector(query, flt=FLT, k=5)) == 1
    builds = store.matrix_builds
    store.search_vector(query, flt=FLT, k=5)
    assert store.matrix_builds == builds  # a segunda pesquisa usou a cache

    store.upsert([make_chunk("segundo documento", doc_id="b")])
    assert len(store.search_vector(query, flt=FLT, k=5)) == 2
    assert store.matrix_builds == builds + 1
    store.delete_document("t1", "a")
    assert len(store.search_vector(query, flt=FLT, k=5)) == 1
    assert store.matrix_builds == builds + 2

    # uma escrita feita por outra ligação ao mesmo ficheiro também invalida a cache
    path = tmp_path / "shared.db"
    reader = SqliteVectorStore(_file_factory(path), DIM)
    writer = SqliteVectorStore(_file_factory(path), DIM)
    reader.upsert([make_chunk("um", doc_id="x")])
    assert len(reader.search_vector(query, flt=FLT, k=5)) == 1
    writer.upsert([make_chunk("dois", doc_id="y")])
    assert len(reader.search_vector(query, flt=FLT, k=5)) == 2


def test_dimension_mismatch_is_rejected_and_upsert_is_atomic() -> None:
    store = SqliteVectorStore(_mem, DIM)
    good = make_chunk("bom", doc_id="a")
    bad = make_chunk("mau", doc_id="b", embedder=FakeEmbedder(dim=8))
    with pytest.raises(ValidationFailed) as exc:
        store.upsert([good, bad])
    assert exc.value.subcode == "embedding_dimension_mismatch"
    assert store.document_hashes("t1", "w1") == {}
    assert store.search_keyword("bom", flt=FLT, k=5) == []


def test_failed_write_rolls_back_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    store = SqliteVectorStore(_mem, DIM)
    store.upsert([make_chunk("já existia", doc_id="old")])
    calls = {"n": 0}
    original = store._keywords.add

    def flaky(chunk_id: str, tenant_id: str, text: str) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("falha a meio")
        original(chunk_id, tenant_id, text)

    monkeypatch.setattr(store._keywords, "add", flaky)
    with pytest.raises(RuntimeError):
        store.upsert([make_chunk("um", doc_id="n1"), make_chunk("dois", doc_id="n2")])
    assert set(store.document_hashes("t1", "w1")) == {"old"}  # nada do lote ficou


def test_upsert_replaces_text_and_index_entries() -> None:
    for backend in ("fts5", "memory"):
        store = SqliteVectorStore(_mem, DIM, keyword_backend=backend)
        first = make_chunk("versão antiga obsoleta", doc_id="d", ordinal=0)
        store.upsert([first])
        newer = first.model_copy(update={"text": "versão nova atualizada"})
        store.upsert([newer])
        assert store.search_keyword("obsoleta", flt=FLT, k=5) == []
        assert _texts(store.search_keyword("atualizada", flt=FLT, k=5)) == [
            "versão nova atualizada"
        ]


def test_search_looks_deeper_when_top_candidates_are_unreadable() -> None:
    hidden = Acl(users=frozenset({"outro"}))
    secret = [
        make_chunk(
            f"orçamento orçamento orçamento segredo {n}",
            doc_id=f"s{n}",
            classification=Classification.RESTRICTED,
            acl=hidden,
        )
        for n in range(30)
    ]
    visible = [make_chunk(f"orçamento aberto {n}", doc_id=f"v{n}") for n in range(3)]
    for backend in ("fts5", "memory"):
        store = SqliteVectorStore(_mem, DIM, keyword_backend=backend)
        store.upsert([*secret, *visible])
        hits = store.search_keyword("orçamento", flt=FLT, k=3)
        assert sorted(_texts(hits)) == sorted(c.text for c in visible), backend
        vector_hits = store.search_vector(EMBEDDER.embed_query("orçamento segredo"), flt=FLT, k=3)
        assert len(vector_hits) == 3
        assert all(
            h.chunk.metadata.classification != Classification.RESTRICTED for h in vector_hits
        )


def test_zero_vector_query_and_empty_store() -> None:
    store = SqliteVectorStore(_mem, DIM)
    assert store.search_vector([0.0] * DIM, flt=FLT, k=3) == []
    store.upsert([make_chunk("algum texto", doc_id="a")])
    hits = store.search_vector([0.0] * DIM, flt=FLT, k=3)
    assert [h.score for h in hits] == [0.0]
    other_tenant = FLT.model_copy(update={"tenant_id": "t9"})
    assert store.search_vector(EMBEDDER.embed_query("texto"), flt=other_tenant, k=3) == []


def test_update_acl_persists_and_init_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "acl.db"
    store = SqliteVectorStore(_file_factory(path), DIM)
    store.init()
    store.upsert([make_chunk("conteúdo partilhado", doc_id="d")])
    assert (
        store.update_acl("t1", "d", Acl(users=frozenset({"alguem"})), Classification.RESTRICTED)
        == 1
    )
    store.close()
    reopened = SqliteVectorStore(_file_factory(path), DIM)
    assert reopened.search_keyword("conteúdo", flt=FLT, k=5) == []
    allowed = FLT.model_copy(update={"user_id": "alguem"})
    assert len(reopened.search_keyword("conteúdo", flt=allowed, k=5)) == 1


def test_invalid_dimension_and_memory_index_edge_cases() -> None:
    with pytest.raises(ValueError):
        SqliteVectorStore(_mem, 0)
    index = Bm25MemoryIndex()
    assert index.search("qualquer", "t1", 5) == []
    index.add("c1", "t1", "texto de exemplo")
    index.remove(["c1", "inexistente"])
    assert index.search("exemplo", "t1", 5) == []
    index.add("c2", "t1", "")
    assert index.search("", "t1", 5) == []
