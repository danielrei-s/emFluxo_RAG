"""Suite de contrato partilhada para implementações de ``VectorStore`` (C6, C10).

Como usar (F5-T01 SQLite, F7-T04 ``PgVectorStore``, F11-T02 store local encriptado):

    from tests.contract.vectorstore_contract import VectorStoreContract

    class TestMyStoreContract(VectorStoreContract):
        supports_local_origin = True  # False no PgVectorStore da central (INV-04)

        def make_store(self) -> VectorStore:
            return MyStore(...)       # uma instância vazia nova por chamada

Cada teste recebe um store novo e vazio. ``make_store`` é um método simples (e não uma fixture)
para poder ser chamado dentro dos testes com Hypothesis, uma vez por exemplo gerado.

O que a suite garante: operações básicas (upsert idempotente, delete, hashes, ACL), isolamento
entre tenants (INV-01), e que toda a leitura coincide com ``policy.can_read`` (INV-02): nenhum
resultado ilegível (correção) e todo o chunk legível que corresponde à pesquisa aparece
(completude). Com ``supports_local_origin = False`` verifica-se que um chunk com
``origin=local`` é recusado com ``ValidationFailed`` (defesa extra de INV-04).
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from rag_core.errors import ValidationFailed
from rag_core.fakes import FakeEmbedder
from rag_core.ids import sha256_hex
from rag_core.interfaces import VectorStore
from rag_core.policy import can_read
from rag_core.testing.chunks import make_chunk
from rag_core.text import normalize_tokens
from rag_core.types import (
    AccessFilter,
    Acl,
    Chunk,
    Classification,
    Origin,
    Role,
    SearchHit,
)

EMBEDDER = FakeEmbedder()
BIG_K = 1000

VOCAB = ("orçamento", "contrato", "férias", "salário", "reunião", "plano")
ACL_CHOICES = (
    Acl(all_members=True),
    Acl(users=frozenset({"u1"})),
    Acl(groups=frozenset({"g1"})),
    Acl(users=frozenset({"outro"}), groups=frozenset({"outro-grupo"})),
    Acl(),
)


def _flt(role: Role = Role.MEMBER, **overrides: Any) -> AccessFilter:
    fields: dict[str, Any] = {
        "tenant_id": "t1",
        "user_id": "u1",
        "role": role,
        "groups": frozenset({"g1"}),
        "origins": frozenset({Origin.CENTRAL, Origin.LOCAL}),
    }
    fields.update(overrides)
    return AccessFilter(**fields)


def _texts(hits: list[SearchHit]) -> list[str]:
    return [h.chunk.text for h in hits]


chunk_specs = st.tuples(
    st.sampled_from(["t1", "t2"]),  # tenant
    st.sampled_from(["w1", "w2"]),  # workspace
    st.sampled_from(list(Classification)),
    st.sampled_from(range(len(ACL_CHOICES))),
    st.sampled_from(list(Origin)),
    st.booleans(),  # local_only
    st.lists(st.sampled_from(VOCAB), min_size=1, max_size=3),  # palavras
)

filters = st.builds(
    lambda role, groups, origins, ex_local, ex_cls, workspaces: AccessFilter(
        tenant_id="t1",
        user_id="u1",
        role=role,
        groups=groups,
        origins=origins,
        exclude_local_only=ex_local,
        exclude_classifications=ex_cls,
        workspace_ids=workspaces,
    ),
    role=st.sampled_from(list(Role)),
    groups=st.sampled_from([frozenset(), frozenset({"g1"})]),
    origins=st.sampled_from(
        [
            frozenset({Origin.CENTRAL}),
            frozenset({Origin.LOCAL}),
            frozenset({Origin.CENTRAL, Origin.LOCAL}),
        ]
    ),
    ex_local=st.booleans(),
    ex_cls=st.frozensets(st.sampled_from(list(Classification))),
    workspaces=st.sampled_from([None, frozenset({"w1"}), frozenset({"w2"})]),
)


class VectorStoreContract:
    """Testes que toda a implementação de ``VectorStore`` tem de passar (ver o módulo)."""

    supports_local_origin: bool = True

    def make_store(self) -> VectorStore:
        raise NotImplementedError("a subclasse tem de implementar make_store()")

    @pytest.fixture
    def store(self) -> VectorStore:
        return self.make_store()

    # ------------------------------------------------------------------ básico

    def test_upsert_then_get(self, store: VectorStore) -> None:
        a = make_chunk("primeiro texto", doc_id="a")
        b = make_chunk("segundo texto", doc_id="b", ordinal=3)
        store.upsert([a, b])
        got = store.get_chunks([b.chunk_id, a.chunk_id], flt=_flt())
        assert [c.chunk_id for c in got] == [b.chunk_id, a.chunk_id]
        assert got[0].text == "segundo texto"
        assert got[0].ordinal == 3
        assert got[0].metadata == b.metadata
        assert store.get_chunks(["inexistente"], flt=_flt()) == []

    def test_upsert_idempotent(self, store: VectorStore) -> None:
        chunk = make_chunk("texto repetido")
        store.upsert([chunk])
        store.upsert([chunk])
        assert len(store.get_chunks([chunk.chunk_id], flt=_flt())) == 1
        assert len(store.search_keyword("repetido", flt=_flt(), k=10)) == 1
        assert len(store.search_vector(EMBEDDER.embed_query("repetido"), flt=_flt(), k=10)) == 1
        assert store.document_hashes("t1", "w1") == {"d1": chunk.metadata.doc_hash}

    def test_upsert_updates_existing_chunk(self, store: VectorStore) -> None:
        old = make_chunk("texto antigo", doc_id="d", ordinal=0)
        store.upsert([old])
        new = old.model_copy(update={"text": "texto novo"})
        store.upsert([new])
        got = store.get_chunks([old.chunk_id], flt=_flt())
        assert [c.text for c in got] == ["texto novo"]

    def test_delete_document_removes_all_chunks(self, store: VectorStore) -> None:
        store.upsert([
            make_chunk("parte um do documento", doc_id="d", ordinal=0),
            make_chunk("parte dois do documento", doc_id="d", ordinal=1),
            make_chunk("outro documento", doc_id="e"),
            make_chunk("documento do tenant b", doc_id="d", tenant_id="t2"),
        ])  # fmt: skip
        assert store.delete_document("t1", "d") == 2
        assert store.delete_document("t1", "d") == 0
        remaining = store.search_keyword("documento", flt=_flt(), k=10)
        assert _texts(remaining) == ["outro documento"]
        assert store.document_hashes("t1", "w1").keys() == {"e"}
        # o mesmo doc_id noutro tenant não é afetado
        other = store.search_keyword("documento", flt=_flt(tenant_id="t2"), k=10)
        assert _texts(other) == ["documento do tenant b"]

    def test_document_hashes(self, store: VectorStore) -> None:
        store.upsert([
            make_chunk("a1", doc_id="a", ordinal=0),
            make_chunk("a2", doc_id="a", ordinal=1),
            make_chunk("b1", doc_id="b"),
            make_chunk("c1", doc_id="c", workspace_id="w2"),
            make_chunk("d1", doc_id="d", tenant_id="t2"),
        ])  # fmt: skip
        assert store.document_hashes("t1", "w1") == {
            "a": sha256_hex("file-a"),
            "b": sha256_hex("file-b"),
        }
        assert store.document_hashes("t1", "w2") == {"c": sha256_hex("file-c")}
        assert store.document_hashes("t1", "vazio") == {}

    def test_update_acl_takes_effect(self, store: VectorStore) -> None:
        store.upsert([
            make_chunk("conteúdo partilhado um", doc_id="d", ordinal=0),
            make_chunk("conteúdo partilhado dois", doc_id="d", ordinal=1),
        ])  # fmt: skip
        query = EMBEDDER.embed_query("conteúdo partilhado")
        assert len(store.search_keyword("conteúdo", flt=_flt(), k=10)) == 2

        restricted = Acl(users=frozenset({"especifico"}))
        assert store.update_acl("t1", "d", restricted, Classification.RESTRICTED) == 2
        assert store.search_keyword("conteúdo", flt=_flt(), k=10) == []
        assert store.search_vector(query, flt=_flt(), k=10) == []
        assert store.update_acl("t2", "d", restricted, Classification.RESTRICTED) == 0
        assert store.update_acl("t1", "nao-existe", restricted, Classification.RESTRICTED) == 0

        allowed = _flt(Role.VIEWER, user_id="especifico")
        assert len(store.search_keyword("conteúdo", flt=allowed, k=10)) == 2
        assert len(store.search_vector(query, flt=allowed, k=10)) == 2

    # --------------------------------------------------------------- pesquisa

    def test_keyword_accent_insensitive(self, store: VectorStore) -> None:
        store.upsert([
            make_chunk("O orçamento de 2026 foi aprovado", doc_id="a"),
            make_chunk("A reunião é na quinta-feira", doc_id="b"),
        ])  # fmt: skip
        assert _texts(store.search_keyword("orcamento", flt=_flt(), k=5)) == [
            "O orçamento de 2026 foi aprovado"
        ]
        assert _texts(store.search_keyword("REUNIAO", flt=_flt(), k=5)) == [
            "A reunião é na quinta-feira"
        ]

    def test_k_respected_and_scores_sorted(self, store: VectorStore) -> None:
        store.upsert([
            make_chunk(f"relatório de vendas número {i} " + "extra " * i, doc_id=f"d{i}")
            for i in range(6)
        ])  # fmt: skip
        query = EMBEDDER.embed_query("relatório de vendas")

        def vector(k: int) -> list[SearchHit]:
            return store.search_vector(query, flt=_flt(), k=k)

        def keyword(k: int) -> list[SearchHit]:
            return store.search_keyword("relatório vendas", flt=_flt(), k=k)

        for search in (vector, keyword):
            top3 = search(3)
            everything = search(BIG_K)
            assert len(top3) == 3
            assert len(everything) == 6
            scores = [h.score for h in everything]
            assert scores == sorted(scores, reverse=True)
            assert [h.chunk.chunk_id for h in top3] == [h.chunk.chunk_id for h in everything[:3]]
            assert len(search(1)) == 1

    def test_search_hits_report_their_stage(self, store: VectorStore) -> None:
        store.upsert([make_chunk("texto de teste")])
        vector = store.search_vector(EMBEDDER.embed_query("texto"), flt=_flt(), k=5)
        keyword = store.search_keyword("texto", flt=_flt(), k=5)
        assert {h.stage for h in vector} == {"vector"}
        assert {h.stage for h in keyword} == {"keyword"}

    def test_empty_store_and_empty_query(self, store: VectorStore) -> None:
        assert store.search_vector(EMBEDDER.embed_query("x"), flt=_flt(), k=5) == []
        assert store.search_keyword("qualquer", flt=_flt(), k=5) == []
        store.upsert([make_chunk("algum texto")])
        assert store.search_keyword("", flt=_flt(), k=5) == []

    # ------------------------------------------------------- isolamento e acesso

    def test_inv01_search_never_crosses_tenants(self, store: VectorStore) -> None:
        secret = make_chunk("CANARIO-segredo do tenant B contrato", doc_id="b", tenant_id="t2")
        store.upsert([secret, make_chunk("contrato normal do tenant A", doc_id="a")])
        flt = _flt()
        query = EMBEDDER.embed_query("CANARIO segredo contrato")
        vector = store.search_vector(query, flt=flt, k=BIG_K)
        keyword = store.search_keyword("CANARIO segredo contrato", flt=flt, k=BIG_K)
        assert _texts(vector) == ["contrato normal do tenant A"]
        assert _texts(keyword) == ["contrato normal do tenant A"]
        assert store.get_chunks([secret.chunk_id], flt=flt) == []
        # e o inverso
        mirror = _flt(tenant_id="t2")
        assert _texts(store.search_keyword("contrato", flt=mirror, k=BIG_K)) == [
            "CANARIO-segredo do tenant B contrato"
        ]

    def test_local_only_excluded_when_requested(self, store: VectorStore) -> None:
        if not self.supports_local_origin:
            # a central recusa qualquer chunk local, incluindo os "só local" (INV-04, INV-05)
            private = make_chunk("nota privada", origin=Origin.LOCAL, local_only=True)
            with pytest.raises(ValidationFailed):
                store.upsert([private])
            assert store.search_keyword("nota", flt=_flt(), k=10) == []
            return
        store.upsert([
            make_chunk("nota privada local", doc_id="l", origin=Origin.LOCAL, local_only=True),
            make_chunk("nota partilhada local", doc_id="m", origin=Origin.LOCAL),
        ])  # fmt: skip
        both = _flt()
        assert len(store.search_keyword("nota", flt=both, k=10)) == 2
        excluded = _flt(exclude_local_only=True)
        assert _texts(store.search_keyword("nota", flt=excluded, k=10)) == ["nota partilhada local"]
        query = EMBEDDER.embed_query("nota")
        assert _texts(store.search_vector(query, flt=excluded, k=10)) == ["nota partilhada local"]

    def test_origins_filter(self, store: VectorStore) -> None:
        central = make_chunk("registo central", doc_id="c")
        local = make_chunk("registo local", doc_id="l", origin=Origin.LOCAL)
        if not self.supports_local_origin:
            with pytest.raises(ValidationFailed):
                store.upsert([local])
            assert store.search_keyword("registo", flt=_flt(), k=10) == []
            store.upsert([central])
            return
        store.upsert([central, local])
        only_central = _flt(origins=frozenset({Origin.CENTRAL}))
        only_local = _flt(origins=frozenset({Origin.LOCAL}))
        assert _texts(store.search_keyword("registo", flt=only_central, k=10)) == [
            "registo central"
        ]
        assert _texts(store.search_keyword("registo", flt=only_local, k=10)) == ["registo local"]
        assert len(store.search_keyword("registo", flt=_flt(), k=10)) == 2
        assert store.search_keyword("registo", flt=_flt(origins=frozenset()), k=10) == []

    def test_exclude_classifications_and_workspace_filters(self, store: VectorStore) -> None:
        store.upsert([
            make_chunk("memorando público", doc_id="p", classification=Classification.PUBLIC),
            make_chunk("memorando interno", doc_id="i", workspace_id="w2"),
        ])  # fmt: skip
        blocked = _flt(exclude_classifications=frozenset({Classification.PUBLIC}))
        assert _texts(store.search_keyword("memorando", flt=blocked, k=10)) == ["memorando interno"]
        only_w2 = _flt(workspace_ids=frozenset({"w2"}))
        assert _texts(store.search_keyword("memorando", flt=only_w2, k=10)) == ["memorando interno"]
        assert store.search_keyword("memorando", flt=_flt(workspace_ids=frozenset()), k=10) == []

    @pytest.mark.parametrize("role", list(Role))
    def test_restricted_needs_explicit_acl_for_every_role(
        self, store: VectorStore, role: Role
    ) -> None:
        store.upsert([
            make_chunk("segredo aberto", doc_id="a", classification=Classification.RESTRICTED,
                       acl=Acl(all_members=True)),
            make_chunk("segredo explícito", doc_id="b", classification=Classification.RESTRICTED,
                       acl=Acl(users=frozenset({"u1"}))),
        ])  # fmt: skip
        assert _texts(store.search_keyword("segredo", flt=_flt(role), k=10)) == [
            "segredo explícito"
        ]

    # ------------------------------------------------------------- propriedade

    def test_inv02_results_satisfy_policy(self) -> None:
        """Correção e completude face a ``policy.can_read`` com chunks e filtros aleatórios.

        A função com ``@given`` é local ao teste: um método ``@given`` herdado por várias
        subclasses falha o health check ``differing_executors`` do Hypothesis.
        """

        @settings(max_examples=60, deadline=None)
        @given(
            specs=st.lists(chunk_specs, min_size=0, max_size=7),
            flt=filters,
            word=st.sampled_from(VOCAB),
        )
        def check(specs: list[tuple[Any, ...]], flt: AccessFilter, word: str) -> None:
            self._check_policy(specs, flt, word)

        check()

    def _check_policy(self, specs: list[tuple[Any, ...]], flt: AccessFilter, word: str) -> None:
        store = self.make_store()
        chunks: list[Chunk] = []
        for index, (
            tenant,
            workspace,
            classification,
            acl_index,
            origin,
            local_only,
            words,
        ) in enumerate(specs):
            chunk = make_chunk(
                " ".join(words),
                doc_id=f"doc{index}",
                tenant_id=tenant,
                workspace_id=workspace,
                classification=classification,
                acl=ACL_CHOICES[acl_index],
                origin=origin,
                local_only=local_only,
            )
            chunks.append(chunk)
        storable = [c for c in chunks if self.supports_local_origin or c.metadata.origin != "local"]
        store.upsert(storable)

        readable = [c for c in storable if can_read(flt, c.metadata)]
        readable_ids = {c.chunk_id for c in readable}

        vector = store.search_vector(EMBEDDER.embed_query(word), flt=flt, k=BIG_K)
        keyword = store.search_keyword(word, flt=flt, k=BIG_K)
        fetched = store.get_chunks([c.chunk_id for c in storable], flt=flt)

        # correção: nenhum resultado que a política proíbe
        for hit in (*vector, *keyword):
            assert can_read(flt, hit.chunk.metadata)
        assert {c.chunk_id for c in fetched} == readable_ids

        # completude: tudo o que é legível e corresponde aparece
        assert {h.chunk.chunk_id for h in vector} == readable_ids
        expected_keyword = {
            c.chunk_id for c in readable if normalize_tokens(word)[0] in normalize_tokens(c.text)
        }
        assert {h.chunk.chunk_id for h in keyword} == expected_keyword
