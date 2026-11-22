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
