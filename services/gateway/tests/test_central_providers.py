"""Testes de F8-T06 (gateway): portas apoiadas na Central API, com cache de 60 s."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from rag_core.clock import FakeClock
from rag_core.errors import NotFound, UpstreamError
from rag_core.interfaces import UsageEvent
from rag_core.types import Role
from rag_gateway.central_providers import (
    CentralDeviceStatusProvider,
    CentralPolicyProvider,
    CentralPrincipalResolver,
    CentralUsageRecorder,
)

URL = "https://central.test"
KEY = SecretStr("chave-interna")
START = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
T1 = "aaaaaaaa-0000-4000-8000-00000000000a"


class Central:
    """Central falsa: guarda os pedidos e responde com o que lhe mandarem."""

    def __init__(self, responses: dict[tuple[str, str], httpx.Response] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.responses = responses or {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["x-internal-key"] == "chave-interna"
        route = (request.method, request.url.path.removeprefix("/internal/v1"))
        response = self.responses.get(route)
        if response is None:
            return httpx.Response(404, json={})
        return response

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def _event(tokens_in: int = 10, tokens_out: int = 5, status: str = "ok") -> UsageEvent:
    return UsageEvent(
        tenant_id=T1,
        user_id="u1",
        device_id=None,
        model="m",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=3,
        ttft_ms=None,
        status=status,  # type: ignore[arg-type]
        at=START,
    )


def test_gateway_providers_cache() -> None:
    clock = FakeClock(START)
    policy = {"tenant_id": T1, "status": "active", "products": ["web"], "monthly_token_quota": 99}
    central = Central(
        {
            ("GET", f"/tenants/{T1}/policy"): httpx.Response(200, json=policy),
            ("GET", "/devices/d1/status"): httpx.Response(200, json={"status": "active"}),
            ("POST", "/principals/resolve"): httpx.Response(
                200,
                json={
                    "tenant_id": T1,
                    "user_id": "u1",
                    "role": "editor",
                    "groups": ["g"],
                    "products": ["web", "local"],
                },
            ),
        }
    )
    policies = CentralPolicyProvider(URL, KEY, clock, central.transport())
    devices = CentralDeviceStatusProvider(URL, KEY, clock, central.transport())
    resolver = CentralPrincipalResolver(URL, KEY, clock, central.transport())
    for _ in range(3):
        assert policies.get(T1).monthly_token_quota == 99
        assert devices.is_active(T1, "u1", "d1") is True
        principal = resolver.resolve({"sub": "u1"}, "d1")
        assert principal is not None and principal.role is Role.EDITOR
    assert len(central.requests) == 3  # uma ida à central por porta
    clock.advance(61)  # a cache expira
    policies.get(T1)
    devices.is_active(T1, "u1", "d1")
    resolver.resolve({"sub": "u1"}, "d1")
    assert len(central.requests) == 6
    sent = json.loads(central.requests[2].content)
    assert sent == {"sub": "u1", "device_id": "d1"}  # o tenant escolhe-o a central, não o token


def test_failures_are_closed() -> None:
    clock = FakeClock(START)
    central = Central(
        {
            ("GET", f"/tenants/{T1}/policy"): httpx.Response(404, json={}),
            ("GET", "/devices/d1/status"): httpx.Response(200, json={"status": "revoked"}),
            ("GET", "/devices/d2/status"): httpx.Response(500, json={}),
            ("POST", "/principals/resolve"): httpx.Response(403, json={}),
        }
    )
    with pytest.raises(NotFound):
        CentralPolicyProvider(URL, KEY, clock, central.transport()).get(T1)
    devices = CentralDeviceStatusProvider(URL, KEY, clock, central.transport())
    assert devices.is_active(T1, "u1", "d1") is False  # revogado
    assert devices.is_active(T1, "u1", "d2") is False  # erro 5xx: fecha
    assert devices.is_active(T1, "u1", "d2") is False
    assert (
        sum(r.url.path.endswith("/d2/status") for r in central.requests) == 2
    )  # sem cache de erros
    assert (
        CentralPrincipalResolver(URL, KEY, clock, central.transport()).resolve({"sub": "x"}, "d")
        is None
    )

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rede", request=request)

    offline = httpx.MockTransport(down)
    assert CentralDeviceStatusProvider(URL, KEY, clock, offline).is_active(T1, "u", "d") is False
    assert CentralPrincipalResolver(URL, KEY, clock, offline).resolve({"sub": "x"}, "d") is None
    with pytest.raises(UpstreamError, match="central_unreachable"):
        CentralPolicyProvider(URL, KEY, clock, offline).get(T1)
    odd = Central({("GET", f"/tenants/{T1}/policy"): httpx.Response(500)})
    with pytest.raises(UpstreamError, match="central_http_500"):
        CentralPolicyProvider(URL, KEY, clock, odd.transport()).get(T1)


def test_usage_recorder_batches_every_five_seconds_and_counts_the_month() -> None:
    clock = FakeClock(START)
    central = Central(
        {
            ("POST", "/usage"): httpx.Response(202, json={"accepted": 2}),
            ("GET", f"/tenants/{T1}/usage/month"): httpx.Response(200, json={"tokens": 1000}),
        }
    )
    recorder = CentralUsageRecorder(URL, KEY, clock, central.transport())
    assert recorder.tokens_used_this_month(T1) == 1000
    recorder.record(_event(10, 5))
    recorder.record(_event(1, 1, status="rejected"))  # recusados não contam
    assert not [r for r in central.requests if r.url.path.endswith("/usage")]  # ainda em buffer
    assert recorder.tokens_used_this_month(T1) == 1015  # central + o que ainda não foi enviado
    clock.advance(5)
    recorder.record(_event(20, 0))  # passaram 5 s: envia o lote
    batches = [json.loads(r.content) for r in central.requests if r.url.path.endswith("/usage")]
    assert [len(b["events"]) for b in batches] == [3]
    assert "content" not in json.dumps(batches).lower().replace("latency", "")
    assert recorder.tokens_used_this_month(T1) == 1035  # já enviado, sem contar duas vezes
    clock.advance(61)  # a cache do total expira e a central passa a incluir tudo
    assert recorder.tokens_used_this_month(T1) == 1000


def test_usage_flush_keeps_events_when_the_central_fails() -> None:
    clock = FakeClock(START)
    state = {"ok": False}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202 if state["ok"] else 503, json={})

    recorder = CentralUsageRecorder(URL, KEY, clock, httpx.MockTransport(handler))
    recorder.record(_event())
    assert recorder.flush() == 0  # 503: nada se perde
    state["ok"] = True
    assert recorder.flush() == 1 and recorder.flush() == 0

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("x", request=request)

    offline = CentralUsageRecorder(URL, KEY, clock, httpx.MockTransport(down))
    offline.record(_event())
    assert offline.flush() == 0
    bad: Any = Central({("GET", f"/tenants/{T1}/usage/month"): httpx.Response(500)})
    with pytest.raises(UpstreamError):
        CentralUsageRecorder(URL, KEY, clock, bad.transport()).tokens_used_this_month(T1)
