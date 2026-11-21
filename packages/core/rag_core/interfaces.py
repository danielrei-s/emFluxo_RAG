"""Interfaces (Protocols) e modelos de política do core (contrato C6, congelado).

Mudar este módulo exige ADR. As implementações vivem noutros módulos ou serviços.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from rag_core.types import (
    AccessFilter,
    Acl,
    ChatMessage,
    Chunk,
    Classification,
    DetectedType,
    Frozen,
    GenerationParams,
    LLMResult,
    Product,
    SearchHit,
    StructuredDocument,
)


class ParseLimits(Frozen):
    """Limites aplicados a um parse (tamanho, páginas, tempo, memória)."""

    max_bytes: int = 50 * 1024 * 1024
    max_pages: int = 2000
    timeout_s: float = 120.0
    max_memory_mb: int = 1536
    max_unzipped_bytes: int = 500 * 1024 * 1024
    ocr: bool = False


@runtime_checkable
class Parser(Protocol):
    """Converte bytes de um ficheiro num ``StructuredDocument``."""

    name: str
    version: str
    supported: frozenset[DetectedType]

    def parse(
        self, data: bytes, *, filename: str, detected: DetectedType, limits: ParseLimits
    ) -> StructuredDocument: ...


@runtime_checkable
class Embedder(Protocol):
    """Gera embeddings de documentos e de perguntas."""

    model_id: str
    dim: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


@runtime_checkable
class VectorStore(Protocol):
    """Índice de chunks. Toda a pesquisa recebe um ``AccessFilter`` obrigatório."""

    def upsert(self, chunks: Sequence[Chunk]) -> None: ...

    def delete_document(self, tenant_id: str, doc_id: str) -> int: ...

    def document_hashes(self, tenant_id: str, workspace_id: str) -> dict[str, str]: ...

    def update_acl(
        self, tenant_id: str, doc_id: str, acl: Acl, classification: Classification
    ) -> int: ...

    def search_vector(
        self, embedding: Sequence[float], *, flt: AccessFilter, k: int
    ) -> list[SearchHit]: ...

    def search_keyword(self, query: str, *, flt: AccessFilter, k: int) -> list[SearchHit]: ...

    def get_chunks(self, chunk_ids: Sequence[str], *, flt: AccessFilter) -> list[Chunk]: ...


@runtime_checkable
class Reranker(Protocol):
    """Reordena resultados de pesquisa por relevância para a pergunta."""

    model_id: str

    def rerank(self, query: str, hits: Sequence[SearchHit], *, top_n: int) -> list[SearchHit]: ...


@runtime_checkable
class LLMProvider(Protocol):
    """Fornecedor de geração de texto."""

    name: str
    is_remote: bool  # True se os dados saem do processo/dispositivo (gateway, HF, central)

    def generate(
        self, messages: Sequence[ChatMessage], *, params: GenerationParams
    ) -> LLMResult: ...

    def stream(
        self, messages: Sequence[ChatMessage], *, params: GenerationParams
    ) -> Iterator[str]: ...


class BlobStore(Protocol):
    """Armazenamento de ficheiros originais."""

    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...


class TokenCounter(Protocol):
    """Conta tokens de um texto."""

    def count(self, text: str) -> int: ...


class Clock(Protocol):
    """Relógio injetável."""

    def now(self) -> datetime: ...  # sempre timezone-aware (UTC)


class RateDecision(Frozen):
    """Decisão de um rate limiter."""

    allowed: bool
    retry_after_s: int = 0


class RateLimiter(Protocol):
    """Limitador de pedidos por chave."""

    def allow(self, key: str, *, cost: int = 1) -> RateDecision: ...


class TenantPolicy(Frozen):
    """Política de um tenant, aplicada no servidor."""

    tenant_id: str
    status: Literal["active", "suspended"] = "active"
    products: frozenset[Product] = frozenset()
    allowed_models: tuple[str, ...] = ("rag-default",)  # 1.º = omissão; resto = fallback
    monthly_token_quota: int = 2_000_000
    rate_per_minute_user: int = 20
    rate_per_minute_tenant: int = 200
    max_prompt_tokens: int = 6000
    max_output_tokens: int = 800
    general_knowledge: Literal["labeled", "forbidden"] = "labeled"
    redact_pii_for_external: bool = True
    conversation_retention_days: Literal[0, 30, 90] = 30
    forced_offline: bool = False
    block_cloud_for: frozenset[Classification] = frozenset({Classification.RESTRICTED})
    wipe_on_revoke: bool = True


class TenantPolicyProvider(Protocol):
    """Obtém a política de um tenant."""

    def get(self, tenant_id: str) -> TenantPolicy: ...


class UsageEvent(Frozen):
    """Evento de consumo registado pelo gateway (sem conteúdo, INV-03)."""

    tenant_id: str
    user_id: str | None
    device_id: str | None
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    ttft_ms: int | None
    status: Literal["ok", "error", "rejected"]
    error_code: str | None = None
    at: datetime


class UsageRecorder(Protocol):
    """Regista consumo e devolve o total mensal."""

    def record(self, event: UsageEvent) -> None: ...

    def tokens_used_this_month(self, tenant_id: str) -> int: ...
