"""Montagem dos modelos reais a partir do ``models.yaml`` (F5-T02/F5-T04)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from rag_core.config import Settings
from rag_core.errors import ValidationFailed
from rag_core.interfaces import Embedder, LLMProvider, Reranker
from rag_core.providers.cross_encoder import CrossEncoderReranker
from rag_core.providers.fastembed_provider import FastEmbedEmbedder
from rag_core.providers.model_registry import ModelRegistry, ModelSpec
from rag_core.providers.openai_compat import OpenAICompatibleEmbedder, OpenAICompatibleLLM
from rag_core.retrieval import NoopReranker

DEFAULT_MODELS_FILE = Path("models.yaml")
LLM_ALIAS = "rag-default"
EMBEDDING_ALIAS = "rag-embed"


@dataclass(frozen=True)
class Models:
    embedder: Embedder
    llm: LLMProvider
    reranker: Reranker
    settings: Settings  # pode ter o rerank desligado quando não há reranker configurado


def _base_url(spec: ModelSpec, settings: Settings) -> str:
    """O URL vem da definição apontada por ``base_url_env`` (ex.: ``RAG_OLLAMA_URL``)."""
    name = (spec.base_url_env or "").removeprefix("RAG_").lower()
    value = getattr(settings, name, None) if name else None
    if not value:
        raise ValidationFailed(subcode="model_base_url_missing")
    return str(value)


def _embedder(alias: str, spec: ModelSpec, settings: Settings) -> Embedder:
    if spec.backend == "openai_compat":
        return OpenAICompatibleEmbedder(
            alias,
            _base_url(spec, settings),
            spec.model,
            dim=spec.dim or 0,
            query_prefix=spec.query_prefix,
            document_prefix=spec.document_prefix,
        )
    if spec.backend == "fastembed":
        cache = (settings.local_data_dir or Path(".rag")) / "models"
        return FastEmbedEmbedder(
            spec.model, cache, spec.query_prefix, spec.document_prefix, spec.dim
        )
    raise ValidationFailed(subcode="unsupported_backend")


def _reranker(spec: ModelSpec, settings: Settings) -> Reranker:
    if spec.kind != "reranker" or spec.backend not in {"fastembed", "sentence_transformers"}:
        raise ValidationFailed(subcode="unsupported_backend")
    backend: Literal["fastembed", "sentence_transformers"] = (
        "fastembed" if spec.backend == "fastembed" else "sentence_transformers"
    )
    return CrossEncoderReranker(spec.model, backend, settings.local_data_dir)


def build_models(
    settings: Settings,
    models_file: Path | None = None,
    *,
    llm_alias: str = LLM_ALIAS,
    embedding_alias: str = EMBEDDING_ALIAS,
    reranker_alias: str | None = None,
) -> Models:
    """LLM, embeddings e (opcionalmente) reranker segundo os aliases do ``models.yaml``."""
    path = models_file or settings.models_file or DEFAULT_MODELS_FILE
    if not path.is_file():
        raise ValidationFailed(subcode="models_file_missing")
    registry = ModelRegistry.from_file(path)
    llm_spec, embed_spec = registry.get(llm_alias), registry.get(embedding_alias)
    if llm_spec.backend != "openai_compat":
        raise ValidationFailed(subcode="unsupported_backend")
    llm = OpenAICompatibleLLM(
        llm_alias, _base_url(llm_spec, settings), llm_spec.model, is_remote=llm_spec.external
    )
    embedder = _embedder(embedding_alias, embed_spec, settings)
    if reranker_alias is not None:
        return Models(embedder, llm, _reranker(registry.get(reranker_alias), settings), settings)
    # sem um reranker configurado, a ordem da fusão basta (e o limiar 0-1 não se aplica)
    retrieval = settings.retrieval.model_copy(update={"rerank_enabled": False})
    tuned = settings.model_copy(update={"retrieval": retrieval})
    return Models(embedder, llm, NoopReranker(), tuned)
