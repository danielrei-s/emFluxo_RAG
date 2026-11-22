"""Testes de F5-T02: tokenizer HF, fastembed e cross-encoder (com modelos falsos)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal

import pytest
from rag_core.providers.cross_encoder import CrossEncoderReranker, sigmoid
from rag_core.providers.fastembed_provider import FastEmbedEmbedder
from rag_core.providers.hf_tokens import HfTokenCounter
from rag_core.testing.chunks import make_chunk
from rag_core.types import SearchHit
from tokenizers import Tokenizer, models, pre_tokenizers

VOCAB = {"[UNK]": 0, "dias": 1, "de": 2, "férias": 3, "por": 4, "ano": 5}


def _tokenizer_file(tmp_path: Path) -> Path:
    tokenizer = Tokenizer(models.WordLevel(VOCAB, unk_token="[UNK]"))  # noqa: S106 - token especial, não é uma palavra-passe
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    path = tmp_path / "tokenizer.json"
    tokenizer.save(str(path))
    return path


def test_hf_token_counter_matches_tokenizer(tmp_path: Path) -> None:
    path = _tokenizer_file(tmp_path)
    counter = HfTokenCounter(path)
    reference = Tokenizer.from_file(str(path))
    for text in ("dias de férias por ano", "", "dias dias dias", "palavra desconhecida aqui"):
        assert counter.count(text) == len(reference.encode(text, add_special_tokens=False).ids)
    assert counter.count("dias de férias por ano") == 5
    assert counter.count("desconhecida") == 1  # [UNK] também conta


class _FakeTextEmbedding:
    def __init__(self) -> None:
        self.seen: list[list[str]] = []

    def embed(self, texts: list[str]) -> Any:
        self.seen.append(list(texts))
        for text in texts:
            yield [3.0 * len(text), 4.0 * len(text), 0.0]


def test_fastembed_embedder_prefixes_normalizes_and_infers_dim(tmp_path: Path) -> None:
    fake = _FakeTextEmbedding()
    captured: dict[str, Any] = {}

    def loader(name: str, cache: Path) -> Any:
        captured.update(name=name, cache=cache)
        return fake

    embedder = FastEmbedEmbedder(
        "intfloat/multilingual-e5-small", tmp_path, "query: ", "passage: ", loader=loader
    )
    assert embedder.dim == 3  # inferida com uma consulta de teste
    assert embedder.model_id == "intfloat/multilingual-e5-small"
    assert captured == {"name": "intfloat/multilingual-e5-small", "cache": tmp_path}
    vector = embedder.embed_query("olá")
    assert vector == pytest.approx([0.6, 0.8, 0.0])
    docs = embedder.embed_documents(["um", "dois"])
    assert fake.seen[-2:] == [["query: olá"], ["passage: um", "passage: dois"]]
    assert all(math.isclose(math.sqrt(sum(x * x for x in d)), 1.0) for d in docs)
    explicit = FastEmbedEmbedder("m", tmp_path, dim=384, loader=lambda *_: _FakeTextEmbedding())
    assert explicit.dim == 384


def test_fastembed_zero_vector_is_not_divided(tmp_path: Path) -> None:
    class Zeros:
        def embed(self, texts: list[str]) -> Any:
            return ([0.0, 0.0] for _ in texts)

    embedder = FastEmbedEmbedder("m", tmp_path, dim=2, loader=lambda *_: Zeros())
    assert embedder.embed_query("x") == [0.0, 0.0]


def _hits(*texts: str) -> list[SearchHit]:
    return [
        SearchHit(chunk=make_chunk(t, doc_id=f"d{i}", embed=False), score=0.1, stage="fused")
        for i, t in enumerate(texts)
    ]


def test_sigmoid_is_stable_and_monotonic() -> None:
    assert sigmoid(0.0) == 0.5
    assert 0.0 < sigmoid(-800.0) < 1e-300 or sigmoid(-800.0) == 0.0
    assert sigmoid(800.0) == 1.0
    assert sigmoid(-2.0) < sigmoid(-1.0) < sigmoid(1.0) < sigmoid(2.0)


@pytest.mark.parametrize("backend", ["fastembed", "sentence_transformers"])
def test_cross_encoder_scores_are_sigmoid_normalized_and_sorted(
    backend: Literal["fastembed", "sentence_transformers"],
) -> None:
    class FakeModel:
        def rerank(self, query: str, documents: list[str]) -> Any:
            return iter([-2.0, 3.0, 0.5])

        def predict(self, pairs: list[list[str]]) -> Any:
            assert all(p[0] == "pergunta" for p in pairs)
            return [-2.0, 3.0, 0.5]

    reranker = CrossEncoderReranker(
        "cross-encoder/teste",
        backend=backend,
        loader=lambda *_: FakeModel(),
    )
    hits = _hits("irrelevante", "muito relevante", "meio relevante")
    ranked = reranker.rerank("pergunta", hits, top_n=2)
    assert [h.chunk.text for h in ranked] == ["muito relevante", "meio relevante"]
    assert [h.score for h in ranked] == pytest.approx([sigmoid(3.0), sigmoid(0.5)])
    assert all(0.0 <= h.score <= 1.0 and h.stage == "reranked" for h in ranked)
    assert reranker.model_id == "cross-encoder/teste"
    assert reranker.rerank("pergunta", [], top_n=3) == []
