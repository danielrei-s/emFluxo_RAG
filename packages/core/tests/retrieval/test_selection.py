"""Testes de F4-T02: seleção de contexto."""

from __future__ import annotations

from collections.abc import Sequence

from rag_core.config import RetrievalSettings, Settings
from rag_core.fakes import FakeReranker
from rag_core.retrieval import NoopReranker, select_context
from rag_core.testing.chunks import make_chunk
from rag_core.types import SearchHit

QUERY = "dias de férias por ano"


def _hit(text: str, doc: str, ordinal: int = 0, score: float = 0.5) -> SearchHit:
    return SearchHit(
        chunk=make_chunk(text, doc_id=doc, ordinal=ordinal, embed=False), score=score, stage="fused"
    )


def _settings(**overrides: object) -> Settings:
    return Settings.for_tests(retrieval=RetrievalSettings(**overrides))  # type: ignore[arg-type]


class SpyReranker(FakeReranker):
    def __init__(self) -> None:
        self.top_n_seen: list[int] = []

    def rerank(self, query: str, hits: Sequence[SearchHit], *, top_n: int) -> list[SearchHit]:
        self.top_n_seen.append(top_n)
        return super().rerank(query, hits, top_n=top_n)


def test_threshold_drops_irrelevant() -> None:
    hits = [
        _hit("dias de férias por ano", "a"),
        _hit("receita de bolo de chocolate", "b"),
        _hit("dias de férias", "c"),
    ]
    selected = select_context(
        QUERY, hits, reranker=FakeReranker(), settings=_settings(min_relevance=0.4)
    )
    assert [h.chunk.metadata.doc_id for h in selected] == ["a", "c"]
    assert all(h.score >= 0.4 and h.stage == "reranked" for h in selected)


def test_per_doc_cap() -> None:
    hits = [_hit(f"dias de férias por ano parte {n}", "mesmo", ordinal=n) for n in range(5)]
    hits.append(_hit("dias de férias por ano outro", "outro"))
    selected = select_context(
        QUERY, hits, reranker=FakeReranker(), settings=_settings(min_relevance=0.1)
    )
    docs = [h.chunk.metadata.doc_id for h in selected]
    assert docs.count("mesmo") == 3
    assert docs.count("outro") == 1


def test_empty_when_nothing_relevant() -> None:
    hits = [_hit("receita de bolo", "a"), _hit("campeonato de futebol", "b")]
    assert select_context(QUERY, hits, reranker=FakeReranker(), settings=_settings()) == []
    assert select_context(QUERY, [], reranker=FakeReranker(), settings=_settings()) == []


def test_inv17_never_more_than_top_n() -> None:
    hits = [_hit(f"dias de férias por ano {n}", f"doc{n}") for n in range(30)]
    for enabled in (True, False):
        settings = _settings(rerank_enabled=enabled, min_relevance=0.0, top_n=4)
        selected = select_context(QUERY, hits, reranker=FakeReranker(), settings=settings)
        assert len(selected) == 4
    reranker = SpyReranker()
    select_context(QUERY, hits, reranker=reranker, settings=_settings(top_n=4))
    assert reranker.top_n_seen == [8]  # pede o dobro ao reranker


def test_rerank_disabled_keeps_fusion_order_without_threshold() -> None:
    hits = [
        _hit("receita de bolo", "a", score=0.03),
        _hit("dias de férias por ano", "b", score=0.02),
    ]
    spy = SpyReranker()
    selected = select_context(QUERY, hits, reranker=spy, settings=_settings(rerank_enabled=False))
    assert [h.chunk.metadata.doc_id for h in selected] == ["a", "b"]
    assert [h.stage for h in selected] == ["fused", "fused"]
    assert spy.top_n_seen == []


def test_noop_reranker_keeps_order_and_limits() -> None:
    hits = [_hit(f"t{n}", f"d{n}", score=1 - n / 10) for n in range(5)]
    out = NoopReranker().rerank("q", hits, top_n=3)
    assert [h.chunk.metadata.doc_id for h in out] == ["d0", "d1", "d2"]
    assert all(h.stage == "reranked" for h in out)
    assert out[0].score == hits[0].score
    assert NoopReranker().model_id == "noop"
