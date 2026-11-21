"""Implementações mínimas dos Protocols, verificadas estaticamente pelo mypy (F1-T02).

Se um Protocol da C6 mudar de assinatura, este ficheiro deixa de passar no mypy.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime

from rag_core.clock import FakeClock, SystemClock
from rag_core.interfaces import (
    BlobStore,
    Clock,
    Embedder,
    LLMProvider,
    ParseLimits,
    Parser,
    RateDecision,
    RateLimiter,
    Reranker,
    TenantPolicy,
    TenantPolicyProvider,
    TokenCounter,
    UsageEvent,
    UsageRecorder,
    VectorStore,
)
from rag_core.types import (
    AccessFilter,
    Acl,
    ChatMessage,
    Chunk,
    Classification,
    DetectedType,
    GenerationParams,
    LLMResult,
    SearchHit,
    StructuredDocument,
)


class MinimalParser:
    name = "minimal"
    version = "0"
    supported: frozenset[DetectedType] = frozenset({DetectedType.TXT})

    def parse(
        self, data: bytes, *, filename: str, detected: DetectedType, limits: ParseLimits
    ) -> StructuredDocument:
        return StructuredDocument(
            detected_type=detected, blocks=(), parser_name=self.name, parser_version=self.version
        )


class MinimalEmbedder:
    model_id = "minimal"
    dim = 2

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.0, 0.0]


class MinimalVectorStore:
    def upsert(self, chunks: Sequence[Chunk]) -> None:
        return None

    def delete_document(self, tenant_id: str, doc_id: str) -> int:
        return 0

    def document_hashes(self, tenant_id: str, workspace_id: str) -> dict[str, str]:
        return {}

    def update_acl(
        self, tenant_id: str, doc_id: str, acl: Acl, classification: Classification
    ) -> int:
        return 0

    def search_vector(
        self, embedding: Sequence[float], *, flt: AccessFilter, k: int
    ) -> list[SearchHit]:
        return []

    def search_keyword(self, query: str, *, flt: AccessFilter, k: int) -> list[SearchHit]:
        return []

    def get_chunks(self, chunk_ids: Sequence[str], *, flt: AccessFilter) -> list[Chunk]:
        return []


class MinimalReranker:
    model_id = "minimal"

    def rerank(self, query: str, hits: Sequence[SearchHit], *, top_n: int) -> list[SearchHit]:
        return list(hits)[:top_n]


class MinimalLLM:
    name = "minimal"
    is_remote = False

    def generate(self, messages: Sequence[ChatMessage], *, params: GenerationParams) -> LLMResult:
        return LLMResult(text="", model=self.name)

    def stream(self, messages: Sequence[ChatMessage], *, params: GenerationParams) -> Iterator[str]:
        yield ""


class MinimalBlobStore:
    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self._data[key] = data

    def get(self, key: str) -> bytes:
        return self._data[key]

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self._data


class MinimalTokenCounter:
    def count(self, text: str) -> int:
        return len(text.split())


class MinimalRateLimiter:
    def allow(self, key: str, *, cost: int = 1) -> RateDecision:
        return RateDecision(allowed=True)


class MinimalPolicyProvider:
    def get(self, tenant_id: str) -> TenantPolicy:
        return TenantPolicy(tenant_id=tenant_id)


class MinimalUsageRecorder:
    def record(self, event: UsageEvent) -> None:
        return None

    def tokens_used_this_month(self, tenant_id: str) -> int:
        return 0


# Atribuições que o mypy verifica: cada classe tem de cumprir o Protocol correspondente.
_parser: Parser = MinimalParser()
_embedder: Embedder = MinimalEmbedder()
_store: VectorStore = MinimalVectorStore()
_reranker: Reranker = MinimalReranker()
_llm: LLMProvider = MinimalLLM()
_blobs: BlobStore = MinimalBlobStore()
_counter: TokenCounter = MinimalTokenCounter()
_limiter: RateLimiter = MinimalRateLimiter()
_policies: TenantPolicyProvider = MinimalPolicyProvider()
_usage: UsageRecorder = MinimalUsageRecorder()
_clocks: tuple[Clock, Clock] = (SystemClock(), FakeClock(datetime(2026, 1, 1, tzinfo=UTC)))
