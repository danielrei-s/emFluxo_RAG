"""Testes da montagem de modelos reais a partir do ``models.yaml``."""

from __future__ import annotations

from pathlib import Path

import pytest
from rag_core.config import Settings
from rag_core.errors import ValidationFailed
from rag_core.providers import OpenAICompatibleEmbedder, OpenAICompatibleLLM
from rag_core.providers.factory import build_models
from rag_core.retrieval import NoopReranker

EXAMPLE = Path(__file__).resolve().parents[4] / "models.example.yaml"


def test_build_models_from_the_example_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_OLLAMA_URL", "http://127.0.0.1:11434/v1")
    settings = Settings.from_env()
    models = build_models(settings, EXAMPLE)
    assert isinstance(models.llm, OpenAICompatibleLLM)
    assert models.llm.name == "rag-default" and models.llm.is_remote is False
    assert isinstance(models.embedder, OpenAICompatibleEmbedder)
    assert (models.embedder.model_id, models.embedder.dim) == ("rag-embed", 1024)
    assert isinstance(models.reranker, NoopReranker)
    assert models.settings.retrieval.rerank_enabled is False  # sem reranker, só a fusão
    assert settings.retrieval.rerank_enabled is True  # a configuração original não é alterada


def test_models_file_can_come_from_the_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RAG_OLLAMA_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("RAG_MODELS_FILE", str(EXAMPLE))
    assert build_models(Settings.from_env()).llm.name == "rag-default"
    monkeypatch.delenv("RAG_MODELS_FILE")
    monkeypatch.chdir(tmp_path)  # sem ficheiro e sem ./models.yaml
    with pytest.raises(ValidationFailed) as exc:
        build_models(Settings.from_env())
    assert exc.value.subcode == "models_file_missing"


MODELS_YAML = """
models:
  llm-a: {kind: llm, backend: openai_compat, base_url_env: RAG_OLLAMA_URL, model: m1, license: MIT}
  emb-onnx: {kind: embedding, backend: fastembed, model: org/e5-small, license: MIT, dim: 384,
             query_prefix: "query: ", document_prefix: "passage: "}
  emb-bad: {kind: embedding, backend: tgi, model: m, license: MIT, dim: 8}
  rerank-ok: {kind: reranker, backend: fastembed, model: org/reranker, license: MIT}
  rerank-bad: {kind: reranker, backend: openai_compat, model: m, license: MIT}
  llm-bad: {kind: llm, backend: fastembed, model: m, license: MIT}
"""


def test_aliases_fastembed_embedder_and_reranker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from typing import Any

    from rag_core.providers import factory

    created: dict[str, Any] = {}

    class FakeEmbedder:
        def __init__(self, *args: Any) -> None:
            created["embedder"] = args

    class FakeReranker:
        def __init__(self, *args: Any) -> None:
            created["reranker"] = args

    monkeypatch.setattr(factory, "FastEmbedEmbedder", FakeEmbedder)
    monkeypatch.setattr(factory, "CrossEncoderReranker", FakeReranker)
    monkeypatch.setenv("RAG_OLLAMA_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("RAG_LOCAL_DATA_DIR", str(tmp_path))
    registry = tmp_path / "models.yaml"
    registry.write_text(MODELS_YAML, encoding="utf-8")
    settings = Settings.from_env()

    models = build_models(
        settings,
        registry,
        llm_alias="llm-a",
        embedding_alias="emb-onnx",
        reranker_alias="rerank-ok",
    )
    assert created["embedder"] == ("org/e5-small", tmp_path / "models", "query: ", "passage: ", 384)
    assert created["reranker"] == ("org/reranker", "fastembed", tmp_path)
    assert isinstance(models.reranker, FakeReranker)
    assert models.settings.retrieval.rerank_enabled is True  # com reranker, o limiar aplica-se

    for kwargs in (
        {"embedding_alias": "emb-bad"},
        {"embedding_alias": "emb-onnx", "reranker_alias": "rerank-bad"},
        {"embedding_alias": "emb-onnx", "llm_alias": "llm-bad"},
    ):
        with pytest.raises(ValidationFailed) as exc:
            build_models(settings, registry, **{"llm_alias": "llm-a", **kwargs})
        assert exc.value.subcode == "unsupported_backend"
