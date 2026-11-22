"""Montagem dos componentes da CLI: store SQLite, modelos (reais ou falsos) e configuração."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from rag_core.config import RetrievalSettings, Settings
from rag_core.fakes import FakeEmbedder, FakeLLMProvider, FakeReranker
from rag_core.interfaces import Embedder, LLMProvider, Reranker
from rag_core.providers.factory import DEFAULT_MODELS_FILE, build_models
from rag_core.stores import SqliteVectorStore

__all__ = ["DEFAULT_MODELS_FILE", "Runtime", "build_runtime"]


@dataclass
class Runtime:
    """Tudo o que os comandos precisam para ingerir e responder."""

    store: SqliteVectorStore
    embedder: Embedder
    llm: LLMProvider
    reranker: Reranker
    settings: Settings


def build_runtime(db: Path, *, fake_models: bool, models_file: Path | None = None) -> Runtime:
    """Abre (ou cria) a base de dados e escolhe os modelos."""
    embedder: Embedder
    llm: LLMProvider
    reranker: Reranker
    if fake_models:
        settings = Settings.for_tests(retrieval=RetrievalSettings(min_relevance=0.05))
        embedder, llm, reranker = FakeEmbedder(), FakeLLMProvider("echo_cite"), FakeReranker()
    else:
        models = build_models(Settings.from_env(), models_file)
        embedder, llm, reranker, settings = (
            models.embedder,
            models.llm,
            models.reranker,
            models.settings,
        )
    db.parent.mkdir(parents=True, exist_ok=True)
    store = SqliteVectorStore(lambda: sqlite3.connect(db), dim=embedder.dim)
    return Runtime(store, embedder, llm, reranker, settings)
