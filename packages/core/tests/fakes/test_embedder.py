"""Testes de ``FakeEmbedder``."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from collections.abc import Sequence

import pytest
from rag_core.fakes import FakeEmbedder
from rag_core.interfaces import Embedder

SAMPLE = "Relatório de vendas do trimestre: orçamento aprovado"


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def _embed_in_subprocess(hashseed: str) -> list[float]:
    code = (
        "import json; from rag_core.fakes import FakeEmbedder; "
        f"print(json.dumps(FakeEmbedder().embed_query({SAMPLE!r})))"
    )
    env = {**os.environ, "PYTHONHASHSEED": hashseed}
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
        env=env, check=True,
    )  # fmt: skip
    return list(json.loads(result.stdout))


def test_fake_embedder_deterministic_across_processes() -> None:
    first = _embed_in_subprocess("0")
    second = _embed_in_subprocess("12345")
    assert first == second
    assert first == FakeEmbedder().embed_query(SAMPLE)


def test_fake_embedder_similar_texts_closer() -> None:
    embedder = FakeEmbedder()
    base = embedder.embed_query("relatório de vendas do trimestre")
    similar = embedder.embed_query("relatorio vendas trimestre")
    different = embedder.embed_query("receita de bolo de chocolate")
    assert _cosine(base, similar) > _cosine(base, different)
    assert _cosine(base, similar) > 0.5


def test_embeddings_are_unit_vectors_with_requested_dimension() -> None:
    embedder = FakeEmbedder(dim=64)
    vectors = embedder.embed_documents(["um texto qualquer", SAMPLE])
    assert len(vectors) == 2
    for vector in vectors:
        assert len(vector) == 64
        assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-9)


def test_query_and_document_embeddings_match_for_same_text() -> None:
    embedder = FakeEmbedder()
    assert embedder.embed_documents([SAMPLE])[0] == embedder.embed_query(SAMPLE)


@pytest.mark.parametrize("text", ["", "   ", "a b c", "!!! ???"])
def test_texts_without_tokens_get_a_fixed_unit_vector(text: str) -> None:
    vector = FakeEmbedder(dim=8).embed_query(text)
    assert vector == [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def test_accents_and_case_do_not_change_the_embedding() -> None:
    embedder = FakeEmbedder()
    assert embedder.embed_query("Orçamento ANUAL") == embedder.embed_query("orcamento anual")


def test_embedder_satisfies_protocol_and_model_id_encodes_dim() -> None:
    embedder = FakeEmbedder(dim=32)
    assert isinstance(embedder, Embedder)
    assert embedder.dim == 32
    assert embedder.model_id == "fake-hash-32"


def test_invalid_dimension_is_rejected() -> None:
    with pytest.raises(ValueError, match="dim"):
        FakeEmbedder(dim=0)
