"""Montagem dos modelos reais a partir do ``models.yaml`` (F5-T02/F5-T04)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rag_core.config import Settings
from rag_core.errors import ValidationFailed
from rag_core.interfaces import Embedder, LLMProvider, Reranker
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


def build_models(settings: Settings, models_file: Path | None = None) -> Models:
    """LLM e embeddings (API OpenAI) segundo os aliases ``rag-default`` e ``rag-embed``."""
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
    tuned = settings.model_copy(update={"retrieval": retrieval})
    return Models(embedder, llm, NoopReranker(), tuned)
