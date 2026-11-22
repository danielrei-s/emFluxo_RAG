"""Montagem dos componentes da CLI: store SQLite, modelos (reais ou falsos) e configuração."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from rag_core.config import RetrievalSettings, Settings
from rag_core.errors import ValidationFailed
from rag_core.fakes import FakeEmbedder, FakeLLMProvider, FakeReranker
from rag_core.interfaces import Embedder, LLMProvider, Reranker
from rag_core.providers import ModelRegistry, ModelSpec, OpenAICompatibleEmbedder
from rag_core.providers.openai_compat import OpenAICompatibleLLM
from rag_core.retrieval import NoopReranker
from rag_core.stores import SqliteVectorStore

DEFAULT_MODELS_FILE = Path("models.yaml")
LLM_ALIAS = "rag-default"
EMBEDDING_ALIAS = "rag-embed"


@dataclass
class Runtime:
    """Tudo o que os comandos precisam para ingerir e responder."""

    store: SqliteVectorStore
    embedder: Embedder
    llm: LLMProvider
    reranker: Reranker
    settings: Settings


def _base_url(spec: ModelSpec, settings: Settings) -> str:
    """O URL vem da definição apontada por ``base_url_env`` (ex.: ``RAG_OLLAMA_URL``)."""
    name = (spec.base_url_env or "").removeprefix("RAG_").lower()
    value = getattr(settings, name, None) if name else None
    if not value:
        raise ValidationFailed(subcode="model_base_url_missing")
    return str(value)


def _real_models(
    settings: Settings, models_file: Path | None
) -> tuple[Embedder, LLMProvider, Reranker, Settings]:
    path = models_file or settings.models_file or DEFAULT_MODELS_FILE
    if not path.is_file():
        raise ValidationFailed(subcode="models_file_missing")
    registry = ModelRegistry.from_file(path)
    llm_spec, embed_spec = registry.get(LLM_ALIAS), registry.get(EMBEDDING_ALIAS)
    for spec in (llm_spec, embed_spec):
        if spec.backend != "openai_compat":
            raise ValidationFailed(subcode="unsupported_backend")
    llm = OpenAICompatibleLLM(
        LLM_ALIAS, _base_url(llm_spec, settings), llm_spec.model, is_remote=llm_spec.external
    )
    embedder = OpenAICompatibleEmbedder(
        EMBEDDING_ALIAS,
        _base_url(embed_spec, settings),
        embed_spec.model,
        dim=embed_spec.dim or 0,
        query_prefix=embed_spec.query_prefix,
        document_prefix=embed_spec.document_prefix,
    )
    # sem um reranker configurado, a ordem da fusão basta (e o limiar 0-1 não se aplica)
    retrieval = settings.retrieval.model_copy(update={"rerank_enabled": False})
    return embedder, llm, NoopReranker(), settings.model_copy(update={"retrieval": retrieval})


def build_runtime(db: Path, *, fake_models: bool, models_file: Path | None = None) -> Runtime:
    """Abre (ou cria) a base de dados e escolhe os modelos."""
    embedder: Embedder
    llm: LLMProvider
    reranker: Reranker
    if fake_models:
        settings = Settings.for_tests(retrieval=RetrievalSettings(min_relevance=0.05))
        embedder, llm, reranker = FakeEmbedder(), FakeLLMProvider("echo_cite"), FakeReranker()
    else:
        embedder, llm, reranker, settings = _real_models(Settings.from_env(), models_file)
    db.parent.mkdir(parents=True, exist_ok=True)
    store = SqliteVectorStore(lambda: sqlite3.connect(db), dim=embedder.dim)
    return Runtime(store, embedder, llm, reranker, settings)
