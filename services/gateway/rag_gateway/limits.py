"""Limites do gateway (F6-T03): rate limit por utilizador e tenant, quota mensal e suspensão."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol

from rag_core.errors import AccessDenied, QuotaExceeded, RateLimited
from rag_core.interfaces import Clock, RateDecision, TenantPolicy, UsageRecorder
from rag_core.types import Principal

WINDOW_S = 60


class RetryableRateLimited(RateLimited):
    """``RateLimited`` com o tempo de espera (o handler problem+json devolve ``Retry-After``)."""

    def __init__(self, retry_after_s: int, detail_id: str | None = None) -> None:
        super().__init__(detail_id)
        self.retry_after_s = retry_after_s


@dataclass
class _Bucket:
    tokens: float
    updated: float


class InMemoryRateLimiter:
    """Token bucket por chave: capacidade = limite por minuto, reposição contínua."""

    def __init__(self, clock: Clock, default_per_minute: int = 60) -> None:
        self._clock = clock
        self._default = default_per_minute
        self._buckets: dict[str, _Bucket] = {}

    def allow(
        self, key: str, *, cost: int = 1, limit_per_minute: int | None = None
    ) -> RateDecision:
        limit = limit_per_minute or self._default
        rate = limit / WINDOW_S  # fichas por segundo
        now = self._clock.now().timestamp()
        bucket = self._buckets.setdefault(key, _Bucket(tokens=float(limit), updated=now))
        bucket.tokens = min(float(limit), bucket.tokens + (now - bucket.updated) * rate)
        bucket.updated = now
        if bucket.tokens >= cost:
            bucket.tokens -= cost
            return RateDecision(allowed=True)
        return RateDecision(
            allowed=False, retry_after_s=max(1, math.ceil((cost - bucket.tokens) / rate))
        )


class RedisLike(Protocol):
    """O mínimo de um cliente Redis que o limitador usa (``redis.Redis`` serve)."""

    def incr(self, name: str) -> int: ...

    def expire(self, name: str, time: int) -> Any: ...


class RedisRateLimiter:
    """Janela fixa de um minuto com ``INCR`` + ``EXPIRE`` (partilhada entre instâncias)."""

    def __init__(self, client: RedisLike, clock: Clock, default_per_minute: int = 60) -> None:
        self._client = client
        self._clock = clock
        self._default = default_per_minute

    def allow(
        self, key: str, *, cost: int = 1, limit_per_minute: int | None = None
    ) -> RateDecision:
        limit = limit_per_minute or self._default
        now = int(self._clock.now().timestamp())
        window = now // WINDOW_S
        name = f"rl:{key}:{window}"
        count = self._client.incr(name)
        if count == 1:
            self._client.expire(name, WINDOW_S * 2)
        if count + cost - 1 <= limit:
            return RateDecision(allowed=True)
        return RateDecision(allowed=False, retry_after_s=(window + 1) * WINDOW_S - now)


class GatewayLimiter:
    """Aplica, por esta ordem: suspensão, quota mensal e limites por utilizador e por tenant."""

    def __init__(
        self,
        limiter: InMemoryRateLimiter | RedisRateLimiter,
        usage: UsageRecorder,
    ) -> None:
        self._limiter = limiter
        self._usage = usage

    def check(self, principal: Principal, policy: TenantPolicy, requested_tokens: int) -> None:
        if policy.status != "active":
            raise AccessDenied("tenant_suspended")
        used = self._usage.tokens_used_this_month(principal.tenant_id)
        if used + requested_tokens > policy.monthly_token_quota:
            raise QuotaExceeded("monthly_quota")
        user = self._limiter.allow(
            f"user:{principal.tenant_id}:{principal.user_id}",
            limit_per_minute=policy.rate_per_minute_user,
        )
        if not user.allowed:  # um pedido recusado não gasta a quota do tenant
            raise RetryableRateLimited(user.retry_after_s, "user_rate")
        tenant = self._limiter.allow(
            f"tenant:{principal.tenant_id}", limit_per_minute=policy.rate_per_minute_tenant
        )
        if not tenant.allowed:
            raise RetryableRateLimited(tenant.retry_after_s, "tenant_rate")
