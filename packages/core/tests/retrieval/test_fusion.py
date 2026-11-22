"""Testes de F4-T01: fusão RRF."""

from __future__ import annotations

import pytest
from rag_core.retrieval.fusion import rrf_fuse
from rag_core.testing.chunks import make_chunk
from rag_core.types import SearchHit


def _hit(name: str, stage: str = "vector", score: float = 0.0) -> SearchHit:
    chunk = make_chunk(f"texto {name}", doc_id=name, embed=False)
    return SearchHit(chunk=chunk, score=score, stage=stage)  # type: ignore[arg-type]


def _ids(hits: list[SearchHit]) -> list[str]:
    return [h.chunk.metadata.doc_id for h in hits]


def test_rrf_hand_computed_scores() -> None:
    a, b, c, d = (_hit(n) for n in "abcd")
    lists = [[a, b, c], [b, a, d], [c, d]]
    fused = rrf_fuse(lists, k=60, limit=10)
    expected = {
        "a": 1 / 61 + 1 / 62,
        "b": 1 / 62 + 1 / 61,
        "c": 1 / 63 + 1 / 61,
        "d": 1 / 63 + 1 / 62,
    }
    assert {n: h.score for n, h in zip(_ids(fused), fused, strict=True)} == pytest.approx(expected)
    # a == b (1/61+1/62) > c (1/63+1/61) > d (1/63+1/62); a e b empatam e saem por chunk_id
    ids = _ids(fused)
    assert ids[2:] == ["c", "d"]
    assert set(ids[:2]) == {"a", "b"}
    assert fused[0].chunk.chunk_id < fused[1].chunk.chunk_id
    assert all(h.stage == "fused" for h in fused)


def test_rrf_uses_k_and_one_based_positions() -> None:
    x = _hit("x")
    assert rrf_fuse([[x]], k=60, limit=5)[0].score == pytest.approx(1 / 61)
    assert rrf_fuse([[x]], k=10, limit=5)[0].score == pytest.approx(1 / 11)
    assert rrf_fuse([[x], [x]], k=60, limit=5)[0].score == pytest.approx(2 / 61)


def test_rrf_dedup_and_deterministic_ties() -> None:
    a, b = _hit("a"), _hit("b")
    # o mesmo chunk repetido na mesma lista só conta uma vez, na primeira posição
    fused = rrf_fuse([[a, a, b]], k=60, limit=10)
    assert _ids(fused) == ["a", "b"]
    assert fused[1].score == pytest.approx(1 / 62)  # b é a 2.ª posição, não a 3.ª

    one, two = _hit("one"), _hit("two")
    forward = rrf_fuse([[one], [two]], limit=10)
    backward = rrf_fuse([[two], [one]], limit=10)
    assert [h.chunk.chunk_id for h in forward] == [h.chunk.chunk_id for h in backward]
    assert [h.chunk.chunk_id for h in forward] == sorted(h.chunk.chunk_id for h in forward)


def test_rrf_limit_and_empty_inputs() -> None:
    hits = [_hit(str(n)) for n in range(5)]
    assert len(rrf_fuse([hits], limit=3)) == 3
    assert rrf_fuse([], limit=3) == []
    assert rrf_fuse([[], []], limit=3) == []
    original = _hit("o", score=9.0)
    assert rrf_fuse([[original]], limit=1)[0].score != 9.0
    assert original.stage == "vector"  # os hits de entrada não são alterados
