"""Testes de ``InMemoryVectorStore`` (a suite de contrato partilhada vem em F1-T05)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rag_core.fakes import FakeEmbedder, InMemoryVectorStore
from rag_core.ids import chunk_id, sha256_hex
from rag_core.interfaces import VectorStore
from rag_core.types import (
    AccessFilter,
    Acl,
    Chunk,
    ChunkMetadata,
    Classification,
    Origin,
    Role,
)

EMBEDDER = FakeEmbedder()


def _chunk(
    text: str,
    *,
    doc_id: str = "d1",
    ordinal: int = 0,
    tenant_id: str = "t1",
    workspace_id: str = "w1",
    classification: Classification = Classification.INTERNAL,
    acl: Acl | None = None,
    embed: bool = True,
    **meta_overrides: Any,
) -> Chunk:
    content_hash = sha256_hex(text)
    fields: dict[str, Any] = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "doc_id": doc_id,
        "source_uri": f"upload://{doc_id}/f.txt",
        "content_hash": content_hash,
        "doc_hash": sha256_hex(f"file-{doc_id}"),
        "acl": acl if acl is not None else Acl(all_members=True),
        "classification": classification,
        "ingested_at": datetime(2026, 1, 1, tzinfo=UTC),
        "parser_version": "1",
        "origin": Origin.CENTRAL,
    }
    fields.update(meta_overrides)
    return Chunk(
        chunk_id=chunk_id(doc_id, ordinal, content_hash),
        ordinal=ordinal,
        text=text,
        metadata=ChunkMetadata(**fields),
        embedding=tuple(EMBEDDER.embed_documents([text])[0]) if embed else None,
        embedding_model=EMBEDDER.model_id if embed else None,
    )


def _flt(role: Role = Role.MEMBER, **overrides: Any) -> AccessFilter:
    fields: dict[str, Any] = {
        "tenant_id": "t1",
        "user_id": "u1",
        "role": role,
        "groups": frozenset({"g1"}),
    }
    fields.update(overrides)
    return AccessFilter(**fields)


def _ids(hits: list[Any]) -> list[str]:
    return [h.chunk.text for h in hits]


def test_store_satisfies_vectorstore_protocol() -> None:
    assert isinstance(InMemoryVectorStore(), VectorStore)


def test_inmemory_store_filters_with_policy() -> None:
    store = InMemoryVectorStore()
    store.upsert([
        _chunk("orçamento anual público", doc_id="pub", classification=Classification.PUBLIC),
        _chunk("orçamento anual interno", doc_id="int"),
        _chunk(
            "orçamento anual restrito de rh",
            doc_id="rh",
            classification=Classification.RESTRICTED,
            acl=Acl(users=frozenset({"outro"})),
        ),
        _chunk("orçamento anual confidencial", doc_id="conf",
               classification=Classification.CONFIDENTIAL),
        _chunk("orçamento anual de outra empresa", doc_id="x", tenant_id="t2"),
        _chunk("orçamento anual local", doc_id="loc", origin=Origin.LOCAL, local_only=True),
    ])  # fmt: skip
    query = EMBEDDER.embed_query("orçamento anual")

    member = _ids(store.search_vector(query, flt=_flt(), k=10))
    assert sorted(member) == [
        "orçamento anual confidencial",
        "orçamento anual interno",
        "orçamento anual público",
    ]
    viewer = _ids(store.search_vector(query, flt=_flt(Role.VIEWER), k=10))
    assert "orçamento anual confidencial" not in viewer
    assert "orçamento anual restrito de rh" not in member  # nem o dono vê sem ACL explícita
    assert "orçamento anual de outra empresa" not in member

    with_local = _flt(origins=frozenset({Origin.CENTRAL, Origin.LOCAL}))
    assert "orçamento anual local" in _ids(store.search_vector(query, flt=with_local, k=10))
    no_local_only = _flt(origins=frozenset({Origin.CENTRAL, Origin.LOCAL}), exclude_local_only=True)
    assert "orçamento anual local" not in _ids(store.search_vector(query, flt=no_local_only, k=10))

    # a pesquisa por palavras-chave aplica exactamente a mesma política
    keyword = _ids(store.search_keyword("orçamento anual", flt=_flt(), k=10))
    assert sorted(keyword) == sorted(member)


def test_other_tenant_canary_never_returned_by_any_read_path() -> None:
    store = InMemoryVectorStore()
    secret = _chunk("CANARIO-segredo do tenant B", doc_id="b", tenant_id="t2")
    store.upsert([secret, _chunk("texto normal do tenant A", doc_id="a")])
    flt = _flt()
    assert store.search_keyword("CANARIO segredo", flt=flt, k=5) == []
    vector_hits = store.search_vector(EMBEDDER.embed_query("CANARIO segredo"), flt=flt, k=5)
    assert [h.chunk.text for h in vector_hits] == ["texto normal do tenant A"]
    assert store.get_chunks([secret.chunk_id], flt=flt) == []


def test_bm25_accent_insensitive() -> None:
    store = InMemoryVectorStore()
    store.upsert([
        _chunk("O orçamento de 2026 foi aprovado", doc_id="a"),
        _chunk("A reunião é na quinta-feira", doc_id="b"),
    ])  # fmt: skip
    hits = store.search_keyword("orcamento", flt=_flt(), k=5)
    assert _ids(hits) == ["O orçamento de 2026 foi aprovado"]
    assert hits[0].stage == "keyword"
    assert hits[0].score > 0
    assert _ids(store.search_keyword("REUNIAO", flt=_flt(), k=5)) == ["A reunião é na quinta-feira"]


def test_keyword_search_edge_cases() -> None:
    store = InMemoryVectorStore()
    assert store.search_keyword("qualquer coisa", flt=_flt(), k=5) == []
    store.upsert([_chunk("texto de exemplo", doc_id="a")])
    assert store.search_keyword("", flt=_flt(), k=5) == []
    assert store.search_keyword("a", flt=_flt(), k=5) == []  # só tokens de 1 carácter
    assert store.search_keyword("inexistente", flt=_flt(), k=5) == []


def test_vector_search_orders_by_cosine_and_respects_k() -> None:
    store = InMemoryVectorStore()
    store.upsert([
        _chunk("relatório de vendas do trimestre", doc_id="a"),
        _chunk("receita de bolo de chocolate", doc_id="b"),
        _chunk("vendas do trimestre aumentaram", doc_id="c"),
    ])  # fmt: skip
    hits = store.search_vector(EMBEDDER.embed_query("relatório de vendas"), flt=_flt(), k=2)
    assert len(hits) == 2
    assert hits[0].chunk.text == "relatório de vendas do trimestre"
    assert hits[0].score >= hits[1].score
    assert all(h.stage == "vector" for h in hits)


def test_vector_search_skips_chunks_without_embedding_and_zero_queries() -> None:
    store = InMemoryVectorStore()
    store.upsert([_chunk("sem embedding", embed=False)])
    assert store.search_vector(EMBEDDER.embed_query("sem embedding"), flt=_flt(), k=5) == []
    store.upsert([_chunk("com embedding", doc_id="b")])
    zero = [0.0] * EMBEDDER.dim
    assert store.search_vector(zero, flt=_flt(), k=5)[0].score == 0.0


def test_upsert_replaces_same_chunk_id() -> None:
    store = InMemoryVectorStore()
    chunk = _chunk("versão única")
    store.upsert([chunk])
    store.upsert([chunk])
    assert len(store.get_chunks([chunk.chunk_id], flt=_flt())) == 1
    assert len(store.search_keyword("versão única", flt=_flt(), k=10)) == 1


def test_delete_document_counts_and_is_tenant_scoped() -> None:
    store = InMemoryVectorStore()
    store.upsert([
        _chunk("primeiro pedaço", doc_id="d", ordinal=0),
        _chunk("segundo pedaço", doc_id="d", ordinal=1),
        _chunk("pedaço de outro tenant", doc_id="d", tenant_id="t2"),
    ])  # fmt: skip
    assert store.delete_document("t1", "d") == 2
    assert store.delete_document("t1", "d") == 0
    assert store.search_keyword("pedaço", flt=_flt(), k=10) == []
    assert len(store.search_keyword("pedaço", flt=_flt(tenant_id="t2"), k=10)) == 1


def test_document_hashes_are_scoped_by_tenant_and_workspace() -> None:
    store = InMemoryVectorStore()
    store.upsert([
        _chunk("a1", doc_id="a", ordinal=0),
        _chunk("a2", doc_id="a", ordinal=1),
        _chunk("b1", doc_id="b"),
        _chunk("c1", doc_id="c", workspace_id="w2"),
        _chunk("d1", doc_id="d", tenant_id="t2"),
    ])  # fmt: skip
    hashes = store.document_hashes("t1", "w1")
    assert hashes == {"a": sha256_hex("file-a"), "b": sha256_hex("file-b")}
    assert store.document_hashes("t1", "nenhum") == {}


def test_update_acl_changes_visibility() -> None:
    store = InMemoryVectorStore()
    store.upsert([
        _chunk("conteúdo partilhado", doc_id="d", ordinal=0),
        _chunk("mais conteúdo partilhado", doc_id="d", ordinal=1),
    ])  # fmt: skip
    assert len(store.search_keyword("conteúdo", flt=_flt(), k=10)) == 2

    restricted = Acl(users=frozenset({"alguem-especifico"}))
    assert store.update_acl("t1", "d", restricted, Classification.RESTRICTED) == 2
    assert store.search_keyword("conteúdo", flt=_flt(), k=10) == []
    assert store.update_acl("t2", "d", restricted, Classification.RESTRICTED) == 0

    allowed = _flt(user_id="alguem-especifico", role=Role.VIEWER)
    assert len(store.search_keyword("conteúdo", flt=allowed, k=10)) == 2


def test_get_chunks_preserves_order_and_filters() -> None:
    store = InMemoryVectorStore()
    a = _chunk("alfa", doc_id="a")
    b = _chunk("beta", doc_id="b")
    hidden = _chunk("gama", doc_id="h", classification=Classification.RESTRICTED,
                    acl=Acl(users=frozenset({"outro"})))  # fmt: skip
    store.upsert([a, b, hidden])
    got = store.get_chunks([b.chunk_id, "inexistente", hidden.chunk_id, a.chunk_id], flt=_flt())
    assert [c.text for c in got] == ["beta", "alfa"]
