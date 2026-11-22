"""Portas do gateway apoiadas na Central API (F8-T06): políticas, consumo, dispositivos, principals.

Todas falam com ``/internal/v1`` com a chave interna e guardam as respostas 60 s. Em caso de
dúvida (erro de rede, resposta inesperada) falham fechadas: dispositivo inativo, sem principal.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import SecretStr
from rag_core.errors import NotFound, UpstreamError
from rag_core.interfaces import Clock, TenantPolicy, UsageEvent
from rag_core.types import Principal, Role

CACHE_TTL_S = 60
FLUSH_INTERVAL_S = 5
MAX_BATCH = 500


class _Central:
    def __init__(
        self,
        base_url: str,
        internal_key: SecretStr,
        clock: Clock,
        transport: httpx.BaseTransport | None,
        timeout_s: float = 5.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"X-Internal-Key": internal_key.get_secret_value()}
        self._clock = clock
        self._http = httpx.Client(timeout=timeout_s, transport=transport)
        self._cache: dict[tuple[Any, ...], tuple[float, Any]] = {}

    def _now(self) -> float:
        return self._clock.now().timestamp()

    def cached(self, key: tuple[Any, ...]) -> tuple[bool, Any]:
        hit = self._cache.get(key)
        if hit is not None and hit[0] > self._now():
            return True, hit[1]
        return False, None

    def store(self, key: tuple[Any, ...], value: Any) -> None:
        self._cache[key] = (self._now() + CACHE_TTL_S, value)

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {**self._headers, **kwargs.pop("headers", {})}
        try:
            return self._http.request(
                method, f"{self._base}/internal/v1{path}", headers=headers, **kwargs
            )
        except httpx.HTTPError as exc:
            raise UpstreamError("central_unreachable") from exc


class CentralPolicyProvider(_Central):
    def get(self, tenant_id: str) -> TenantPolicy:
        hit, value = self.cached(("policy", tenant_id))
        if hit:
            return value  # type: ignore[no-any-return]
        response = self.request("GET", f"/tenants/{tenant_id}/policy")
        if response.status_code == 404:
            raise NotFound()
        if response.status_code != 200:
            raise UpstreamError(f"central_http_{response.status_code}")
        policy = TenantPolicy.model_validate(response.json())
        self.store(("policy", tenant_id), policy)
        return policy


class CentralDeviceStatusProvider(_Central):
    def is_active(self, tenant_id: str, user_id: str, device_id: str) -> bool:
        key = ("device", tenant_id, user_id, device_id)
        hit, value = self.cached(key)
        if hit:
            return bool(value)
        try:
            response = self.request(
                "GET",
                f"/devices/{device_id}/status",
                params={"tenant_id": tenant_id, "user_id": user_id},
            )
        except UpstreamError:
            return False  # sem resposta da central, o dispositivo não é aceite
        active = response.status_code == 200 and response.json().get("status") == "active"
        if response.status_code in (200, 404):  # só se guardam respostas definitivas
            self.store(key, active)
        return active


class CentralPrincipalResolver(_Central):
    def resolve(self, claims: Mapping[str, Any], device_id: str) -> Principal | None:
        sub = str(claims.get("sub") or "")
        key = ("principal", sub, device_id)
        hit, value = self.cached(key)
        if hit:
            return value  # type: ignore[no-any-return]
        try:
            response = self.request(
                "POST", "/principals/resolve", json={"sub": sub, "device_id": device_id}
            )
        except UpstreamError:
            return None
        if response.status_code != 200:
            if response.status_code in (400, 403, 404):
                self.store(key, None)
            return None
        data = response.json()
        principal = Principal(
            tenant_id=data["tenant_id"],
            user_id=data["user_id"],
            role=Role(data["role"]),
            groups=frozenset(data["groups"]),
            products=frozenset(data["products"]),
        )
        self.store(key, principal)
        return principal


@dataclass
class _Month:
    central_total: int
    fetched_at: float
    sent_since: int = 0


class CentralUsageRecorder(_Central):
    """Guarda os eventos em memória e envia-os em lote a cada 5 s (ou com ``flush``)."""

    def __init__(
        self,
        base_url: str,
        internal_key: SecretStr,
        clock: Clock,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(base_url, internal_key, clock, transport)
        self._buffer: list[UsageEvent] = []
        self._last_flush = self._now()
        self._months: dict[str, _Month] = {}

    def record(self, event: UsageEvent) -> None:
        self._buffer.append(event)
        if self._now() - self._last_flush >= FLUSH_INTERVAL_S or len(self._buffer) >= MAX_BATCH:
            self.flush()

    def flush(self) -> int:
        """Envia o buffer; se a central falhar os eventos ficam para a próxima tentativa."""
        self._last_flush = self._now()
        sent = 0
        while self._buffer:
            batch = self._buffer[:MAX_BATCH]
            body = json.dumps({"events": [e.model_dump(mode="json") for e in batch]})
            try:
                response = self.request(
                    "POST", "/usage", content=body, headers={"Content-Type": "application/json"}
                )
            except UpstreamError:
                return sent
            if response.status_code != 202:
                return sent
            del self._buffer[: len(batch)]
            sent += len(batch)
            for event in batch:
                month = self._months.get(event.tenant_id)
                if month is not None and event.status == "ok":
                    month.sent_since += event.tokens_in + event.tokens_out
        return sent

    def tokens_used_this_month(self, tenant_id: str) -> int:
        month = self._months.get(tenant_id)
        if month is None or self._now() - month.fetched_at >= CACHE_TTL_S:
            response = self.request("GET", f"/tenants/{tenant_id}/usage/month")
            if response.status_code != 200:
                raise UpstreamError(f"central_http_{response.status_code}")
            month = _Month(int(response.json()["tokens"]), self._now())
            self._months[tenant_id] = month
        pending = sum(
            e.tokens_in + e.tokens_out
            for e in self._buffer
            if e.tenant_id == tenant_id and e.status == "ok"
        )
        return month.central_total + month.sent_since + pending
