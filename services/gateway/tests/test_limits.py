"""Testes de F6-T03: limites do gateway (rate limit, quota mensal, suspensão, Retry-After)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from rag_core.clock import FakeClock
from rag_core.config import Settings
from rag_core.errors import AccessDenied, QuotaExceeded, RateLimited
from rag_core.interfaces import TenantPolicy, UsageEvent
from rag_core.types import Principal, Role
from rag_gateway.app import create_app
from rag_gateway.limits import (
    GatewayLimiter,
    InMemoryRateLimiter,
    RedisRateLimiter,
    RetryableRateLimited,
)
from rag_gateway.usage import InMemoryUsageRecorder

# O TestClient usa um par de sockets internos (loopback); nada sai da máquina.
pytestmark = pytest.mark.enable_socket
START = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
ALICE = Principal(tenant_id="t1", user_id="alice", role=Role.MEMBER)
BOB = Principal(tenant_id="t1", user_id="bob", role=Role.MEMBER)
OTHER_TENANT = Principal(tenant_id="t2", user_id="alice", role=Role.MEMBER)


def _event(
    tenant: str, tokens_in: int, tokens_out: int, at: datetime, status: str = "ok"
) -> UsageEvent:
    return UsageEvent(
        tenant_id=tenant, user_id="alice", device_id=None, model="m", tokens_in=tokens_in,
        tokens_out=tokens_out, latency_ms=10, ttft_ms=None, status=status, at=at,  # type: ignore[arg-type]
    )  # fmt: skip


def test_bucket_refill_with_fake_clock() -> None:
    clock = FakeClock(START)
    limiter = InMemoryRateLimiter(clock)
    assert all(limiter.allow("k", limit_per_minute=60).allowed for _ in range(60))  # a capacidade
    denied = limiter.allow("k", limit_per_minute=60)
    assert denied.allowed is False and denied.retry_after_s == 1  # 1 ficha por segundo
    clock.advance(1)
    assert limiter.allow("k", limit_per_minute=60).allowed is True
    assert limiter.allow("k", limit_per_minute=60).allowed is False
    clock.advance(10)
    assert limiter.allow("k", cost=10, limit_per_minute=60).allowed is True
    big = limiter.allow("k", cost=30, limit_per_minute=60)
    assert big.allowed is False and big.retry_after_s == 30
    clock.advance(3600)  # nunca acumula mais do que a capacidade
    assert limiter.allow("k", cost=61, limit_per_minute=60).allowed is False
    assert limiter.allow("k", cost=60, limit_per_minute=60).allowed is True


def test_user_and_tenant_limits_independent() -> None:
    clock = FakeClock(START)
    limits = GatewayLimiter(InMemoryRateLimiter(clock), InMemoryUsageRecorder(clock))
    policy = TenantPolicy(tenant_id="t1", rate_per_minute_user=2, rate_per_minute_tenant=3)
    limits.check(ALICE, policy, 10)
    limits.check(ALICE, policy, 10)
    with pytest.raises(RetryableRateLimited) as user:  # a Alice esgotou o limite dela
        limits.check(ALICE, policy, 10)
    assert user.value.detail_id == "user_rate" and user.value.retry_after_s >= 1
    limits.check(BOB, policy, 10)  # o Bob não é afetado; é o 3.º pedido do tenant
    with pytest.raises(RetryableRateLimited) as tenant:  # agora o tenant está esgotado
        limits.check(BOB, policy, 10)
    assert tenant.value.detail_id == "tenant_rate"
    # outro tenant tem os seus próprios baldes
    limits.check(OTHER_TENANT, policy.model_copy(update={"tenant_id": "t2"}), 10)
    clock.advance(60)
    limits.check(ALICE, policy, 10)  # o balde encheu


def test_tenant_limit_blocks_even_when_the_user_has_room() -> None:
    clock = FakeClock(START)
    limits = GatewayLimiter(InMemoryRateLimiter(clock), InMemoryUsageRecorder(clock))
    policy = TenantPolicy(tenant_id="t1", rate_per_minute_user=50, rate_per_minute_tenant=1)
    limits.check(ALICE, policy, 1)
    with pytest.raises(RetryableRateLimited) as exc:
        limits.check(BOB, policy, 1)
    assert exc.value.detail_id == "tenant_rate"


def test_quota_exceeded() -> None:
    clock = FakeClock(START)
    usage = InMemoryUsageRecorder(clock)
    limits = GatewayLimiter(InMemoryRateLimiter(clock), usage)
    policy = TenantPolicy(tenant_id="t1", monthly_token_quota=1000)
    usage.record(_event("t1", 300, 400, START))
    limits.check(ALICE, policy, 300)  # 700 usados + 300 pedidos = 1000: cabe
    with pytest.raises(QuotaExceeded):
        limits.check(ALICE, policy, 301)
    usage.record(_event("t1", 100, 100, START, status="error"))  # falhas não contam
    limits.check(ALICE, policy, 300)
    usage.record(_event("t2", 5000, 5000, START))  # outro tenant não conta
    limits.check(ALICE, policy, 300)
    assert usage.tokens_used_this_month("t1") == 700


def test_usage_total_resets_with_the_calendar_month() -> None:
    clock = FakeClock(START)
    usage = InMemoryUsageRecorder(clock)
    usage.record(_event("t1", 500, 500, START))
    usage.record(_event("t1", 700, 0, datetime(2026, 4, 30, 23, 59, tzinfo=UTC)))
    assert usage.tokens_used_this_month("t1") == 1000
    clock.set(datetime(2026, 6, 1, tzinfo=UTC))
    assert usage.tokens_used_this_month("t1") == 0
    assert len(usage.events) == 2


def test_suspended_tenant_forbidden() -> None:
    clock = FakeClock(START)
    limits = GatewayLimiter(InMemoryRateLimiter(clock), InMemoryUsageRecorder(clock))
    with pytest.raises(AccessDenied) as exc:
        limits.check(ALICE, TenantPolicy(tenant_id="t1", status="suspended"), 1)
    assert exc.value.detail_id == "tenant_suspended"


def test_retry_after_header() -> None:
    clock = FakeClock(START)
    limits = GatewayLimiter(InMemoryRateLimiter(clock), InMemoryUsageRecorder(clock))
    policy = TenantPolicy(tenant_id="t1", rate_per_minute_user=1)
    app = create_app(Settings.for_tests())

    @app.get("/limited")
    def limited() -> dict[str, str]:
        limits.check(ALICE, policy, 1)
        return {"ok": "sim"}

    @app.get("/suspended")
    def suspended() -> None:
        limits.check(ALICE, policy.model_copy(update={"status": "suspended"}), 1)

    @app.get("/quota")
    def quota() -> None:
        limits.check(ALICE, policy.model_copy(update={"monthly_token_quota": 0}), 5)

    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/limited").status_code == 200
    second = client.get("/limited")
    assert second.status_code == 429
    assert second.headers["retry-after"] == "60"
    assert second.json()["code"] == "rate_limited" and second.json()["subcode"] == "user_rate"
    forbidden = client.get("/suspended")
    assert (forbidden.status_code, forbidden.json()["subcode"]) == (403, "tenant_suspended")
    over = client.get("/quota")
    assert (over.status_code, over.json()["code"]) == (429, "quota_exceeded")
    assert "retry-after" not in over.headers


class FakeRedis:
    """Só ``INCR`` e ``EXPIRE``, como o limitador precisa."""

    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def incr(self, name: str) -> int:
        self.counters[name] = self.counters.get(name, 0) + 1
        return self.counters[name]

    def expire(self, name: str, time: int) -> Any:
        self.ttls[name] = time


def test_redis_rate_limiter_fixed_window() -> None:
    clock = FakeClock(datetime(2026, 5, 10, 12, 0, 20, tzinfo=UTC))
    client = FakeRedis()
    limiter = RedisRateLimiter(client, clock)
    assert [limiter.allow("k", limit_per_minute=3).allowed for _ in range(3)] == [True] * 3
    denied = limiter.allow("k", limit_per_minute=3)
    assert denied.allowed is False and denied.retry_after_s == 40  # até ao fim do minuto
    assert len(client.ttls) == 1 and set(client.ttls.values()) == {120}  # EXPIRE só na 1.ª vez
    clock.advance(40)
    assert limiter.allow("k", limit_per_minute=3).allowed is True  # janela nova
    assert limiter.allow("outra", limit_per_minute=3).allowed is True  # chaves independentes
    assert RateLimited.code == "rate_limited"
    assert RetryableRateLimited(5).retry_after_s == 5
