"""Testes de ``rag_core.interfaces`` (contratos C6)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from rag_core.clock import FakeClock, SystemClock
from rag_core.interfaces import (
    BlobStore,
    Clock,
    Embedder,
    LLMProvider,
    ParseLimits,
    Parser,
    RateDecision,
    Reranker,
    TenantPolicy,
    UsageEvent,
    VectorStore,
)
from rag_core.types import Classification, Product

from .typing.check_protocols import (
    MinimalEmbedder,
    MinimalLLM,
    MinimalParser,
    MinimalReranker,
    MinimalVectorStore,
)

AT = datetime(2026, 1, 1, tzinfo=UTC)


def test_runtime_checkable_protocols_accept_minimal_impls() -> None:
    assert isinstance(MinimalParser(), Parser)
    assert isinstance(MinimalEmbedder(), Embedder)
    assert isinstance(MinimalVectorStore(), VectorStore)
    assert isinstance(MinimalReranker(), Reranker)
    assert isinstance(MinimalLLM(), LLMProvider)


def test_runtime_checkable_protocols_reject_objects_missing_members() -> None:
    class NotAParser:
        name = "x"

    assert not isinstance(NotAParser(), Parser)
    assert not isinstance(object(), VectorStore)
    assert not isinstance(object(), LLMProvider)


def test_tenant_policy_defaults() -> None:
    policy = TenantPolicy(tenant_id="t1")
    assert policy.status == "active"
    assert policy.products == frozenset()
    assert policy.allowed_models == ("rag-default",)
    assert policy.monthly_token_quota == 2_000_000
    assert (policy.rate_per_minute_user, policy.rate_per_minute_tenant) == (20, 200)
    assert (policy.max_prompt_tokens, policy.max_output_tokens) == (6000, 800)
    assert policy.general_knowledge == "labeled"
    assert policy.redact_pii_for_external is True
    assert policy.conversation_retention_days == 30
    assert policy.forced_offline is False
    assert policy.block_cloud_for == frozenset({Classification.RESTRICTED})
    assert policy.wipe_on_revoke is True


def test_tenant_policy_rejects_invalid_literals() -> None:
    with pytest.raises(ValidationError):
        TenantPolicy(tenant_id="t", status="deleted")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        TenantPolicy(tenant_id="t", conversation_retention_days=45)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        TenantPolicy(tenant_id="t", general_knowledge="always")  # type: ignore[arg-type]


def test_tenant_policy_accepts_products_and_is_frozen() -> None:
    policy = TenantPolicy(tenant_id="t", products=frozenset({Product.WEB, Product.LOCAL}))
    assert Product.LOCAL in policy.products
    with pytest.raises(ValidationError):
        policy.status = "suspended"


def test_parse_limits_defaults() -> None:
    limits = ParseLimits()
    assert limits.max_bytes == 50 * 1024 * 1024
    assert limits.max_pages == 2000
    assert limits.timeout_s == 120.0
    assert limits.max_memory_mb == 1536
    assert limits.max_unzipped_bytes == 500 * 1024 * 1024
    assert limits.ocr is False


def test_rate_decision_and_usage_event_models() -> None:
    assert RateDecision(allowed=True).retry_after_s == 0
    fields = {
        "tenant_id": "t",
        "user_id": None,
        "device_id": None,
        "model": "m",
        "tokens_in": 1,
        "tokens_out": 2,
        "latency_ms": 3,
        "ttft_ms": None,
        "at": AT,
    }
    assert UsageEvent(**fields, status="ok").error_code is None  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        UsageEvent(**fields, status="weird")  # type: ignore[arg-type]


def test_system_and_fake_clocks_satisfy_the_clock_protocol() -> None:
    clocks: list[Clock] = [SystemClock(), FakeClock()]
    assert all(c.now().tzinfo is not None for c in clocks)


def test_blob_store_is_a_plain_protocol() -> None:
    # BlobStore não é runtime_checkable na C6: só serve para verificação estática.
    with pytest.raises(TypeError):
        isinstance(object(), BlobStore)  # type: ignore[misc]
