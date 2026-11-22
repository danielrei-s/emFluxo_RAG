"""Testes de F4-T01: pesquisa híbrida."""

from __future__ import annotations

from rag_core.config import RetrievalSettings, Settings
from rag_core.fakes import FakeEmbedder, InMemoryVectorStore
from rag_core.retrieval import HybridRetriever
from rag_core.testing import corpus
from rag_core.types import AccessFilter, Origin


def _flt(tenant: str, user: str) -> AccessFilter:
    return AccessFilter.for_principal(
        corpus.principal_for(tenant, user), origins=frozenset({Origin.CENTRAL})
    )


def _retriever(store: InMemoryVectorStore, **retrieval: object) -> HybridRetriever:
    settings = Settings.for_tests(retrieval=RetrievalSettings(**retrieval))  # type: ignore[arg-type]
    return HybridRetriever(store, FakeEmbedder(), settings)


def test_hybrid_finds_vacation_policy_top5(indexed_store: InMemoryVectorStore) -> None:
    hits = _retriever(indexed_store).retrieve("dias de férias", _flt("aurora", "ana"))
    a01 = corpus.source_file_for("A01").doc_id
    assert a01 in [h.chunk.metadata.doc_id for h in hits[:5]]
    assert all(h.stage == "fused" for h in hits)
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


def test_hybrid_respects_rerank_top_in(indexed_store: InMemoryVectorStore) -> None:
    hits = _retriever(indexed_store, rerank_top_in=3).retrieve(
        "prazo de pagamento", _flt("aurora", "ana")
    )
    assert len(hits) == 3


def test_inv01_hybrid_respects_tenant_filter(indexed_store: InMemoryVectorStore) -> None:
    retriever = _retriever(indexed_store)
    tenant_a = corpus.tenant_id("aurora")
    tenant_b = corpus.tenant_id("boreal")
    from_a = retriever.retrieve("CANARIO TENANT B consultoria sénior férias", _flt("aurora", "ana"))
    assert from_a
    assert {h.chunk.metadata.tenant_id for h in from_a} == {tenant_a}
    assert all("CANARIO-TENANT-B" not in h.chunk.text for h in from_a)
    from_b = retriever.retrieve("consultoria sénior hora", _flt("boreal", "bruno"))
    assert from_b
    assert {h.chunk.metadata.tenant_id for h in from_b} == {tenant_b}
    salary = retriever.retrieve("salário Técnico Comercial 1350", _flt("boreal", "bruno"))
    assert {h.chunk.metadata.tenant_id for h in salary} <= {tenant_b}  # a vetorial devolve vizinhos
    assert all("1350" not in h.chunk.text and "CANARIO-RH" not in h.chunk.text for h in salary)


def test_injection_flagged_chunk_downweighted(indexed_store: InMemoryVectorStore) -> None:
    query, flt = "campanha de regresso às aulas em setembro", _flt("aurora", "ana")
    full = _retriever(indexed_store, injection_downweight=1.0).retrieve(query, flt)
    half = _retriever(indexed_store, injection_downweight=0.5).retrieve(query, flt)

    def flagged(hits: list) -> dict[str, float]:  # type: ignore[type-arg]
        return {
            h.chunk.chunk_id: h.score
            for h in hits
            if "suspected_injection" in h.chunk.metadata.flags
        }

    before, after = flagged(full), flagged(half)
    assert before
    assert after.keys() == before.keys()
    for chunk_id, score in before.items():
        assert after[chunk_id] == score * 0.5
    clean_full = {h.chunk.chunk_id: h.score for h in full if h.chunk.chunk_id not in before}
    clean_half = {h.chunk.chunk_id: h.score for h in half if h.chunk.chunk_id not in before}
    assert clean_full == clean_half  # só os chunks suspeitos são penalizados
