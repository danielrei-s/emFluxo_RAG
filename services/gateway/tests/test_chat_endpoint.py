"""Testes de F6-T05: ``POST /v1/chat/completions`` (INV-03, INV-09, quotas e streaming)."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from rag_core.auth import CompositeVerifier, JwksVerifier
from rag_core.clock import FakeClock
from rag_core.config import Settings
from rag_core.errors import UpstreamError
from rag_core.fakes import FakeLLMProvider
from rag_core.interfaces import TenantPolicy
from rag_core.policy_provider import StaticPolicyProvider
from rag_core.testing.jwt import AUDIENCE, ISSUER, JwtFactory
from rag_core.types import ChatMessage, GenerationParams, LLMResult
from rag_gateway.app import GatewayDeps, create_app
from rag_gateway.auth import Authenticator
from rag_gateway.chat import ChatService
from rag_gateway.limits import GatewayLimiter, InMemoryRateLimiter
from rag_gateway.ports import FakeDeviceStatusProvider, FakePrincipalResolver
from rag_gateway.routing import ModelRouter
from rag_gateway.usage import InMemoryUsageRecorder

# O TestClient usa um par de sockets internos (loopback); nada sai da máquina.
pytestmark = pytest.mark.enable_socket

CENTRAL_JWKS = "https://central.test/jwks.json"
CANARY = "CANARIO-conteudo-secreto-7731"
START = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
BODY = {"messages": [{"role": "user", "content": "Olá, tudo bem?"}]}


class Failing:
    name = "failing"
    is_remote = False

    def generate(self, messages: Sequence[ChatMessage], *, params: GenerationParams) -> LLMResult:
        raise UpstreamError("http_500")

    def stream(self, messages: Sequence[ChatMessage], *, params: GenerationParams) -> Iterator[str]:
        raise UpstreamError("http_500")
        yield ""  # pragma: no cover


class Interrupted(FakeLLMProvider):
    def stream(self, messages: Sequence[ChatMessage], *, params: GenerationParams) -> Iterator[str]:
        yield "parcial "
        raise UpstreamError("stream_interrupted")


class Env:
    def __init__(self, providers: dict[str, Any], policy: TenantPolicy) -> None:
        self.central = JwtFactory()
        clock = FakeClock(START)
        self.usage = InMemoryUsageRecorder(clock)
        http = httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=self.central.jwks()))
        )
        verifier = CompositeVerifier(
            {ISSUER: JwksVerifier(CENTRAL_JWKS, ISSUER, AUDIENCE, http=http)}
        )
        authenticator = Authenticator(
            verifier,
            central_issuer=ISSUER,
            resolver=FakePrincipalResolver(),
            device_status=FakeDeviceStatusProvider(),
        )
        service = ChatService(
            policies=StaticPolicyProvider({"t1": policy}),
            limiter=GatewayLimiter(InMemoryRateLimiter(clock), self.usage),
            usage=self.usage,
            router=ModelRouter(providers, clock),
            clock=clock,
        )
        app = create_app(
            Settings.for_tests(), GatewayDeps(authenticator=authenticator, chat=service)
        )
        self.client = TestClient(app, raise_server_exceptions=False)
        self.headers = {"Authorization": f"Bearer {self.central.issue()}"}

    def post(self, body: dict[str, Any]) -> httpx.Response:
        response: httpx.Response = self.client.post(
            "/v1/chat/completions", json=body, headers=self.headers
        )
        return response


def _env(text: str = "Resposta de teste", **policy: Any) -> Env:
    policy.setdefault("allowed_models", ("primary", "secondary"))
    providers = {
        "primary": FakeLLMProvider("scripted", responses=[text] * 20),
        "secondary": FakeLLMProvider("scripted", responses=["do secundário"] * 20),
    }
    return Env(providers, TenantPolicy(tenant_id="t1", **policy))


def test_non_stream_happy_path() -> None:
    env = _env("Resposta de teste")
    response = env.post(BODY)
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "chat.completion" and data["model"] == "primary"
    assert data["choices"][0]["message"] == {"role": "assistant", "content": "Resposta de teste"}
    assert data["choices"][0]["finish_reason"] == "stop"
    usage = data["usage"]
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"] > 0
    assert response.headers["x-model-alias"] == "primary" and response.headers["x-request-id"]
    chosen = env.post({**BODY, "model": "secondary", "max_tokens": 50, "temperature": 0.5})
    assert chosen.json()["choices"][0]["message"]["content"] == "do secundário"
    assert chosen.headers["x-model-alias"] == "secondary"


def _sse(response: httpx.Response) -> list[str]:
    return [line for line in response.text.split("\n\n") if line]


def test_stream_happy_path() -> None:
    env = _env("uma resposta em vários pedaços")
    response = env.post({**BODY, "stream": True})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-model-alias"] == "primary"
    events = _sse(response)
    assert events[-1] == "data: [DONE]"
    chunks = [json.loads(e.removeprefix("data: ")) for e in events[:-1]]
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert all(c["object"] == "chat.completion.chunk" for c in chunks)
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert text == "uma resposta em vários pedaços"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    event = env.usage.events[-1]
    assert event.status == "ok" and event.ttft_ms is not None and event.tokens_out > 0


@pytest.mark.parametrize("field", ["tools", "functions", "tool_choice", "function_call"])
def test_inv09_tools_rejected(field: str) -> None:
    env = _env()
    response = env.post({**BODY, field: []})
    assert response.status_code == 400
    assert response.json()["code"] == "unsupported_feature"
    assert env.usage.events[-1].status == "rejected"


def test_inv09_image_content_rejected() -> None:
    env = _env()
    image = [{"type": "image_url", "image_url": {"url": "https://x.test/a.png"}}]
    response = env.post({"messages": [{"role": "user", "content": image}]})
    assert response.status_code == 400
    assert (response.json()["code"], response.json()["subcode"]) == (
        "unsupported_feature",
        "non_text_content",
    )


def test_unknown_fields_and_limits_are_400() -> None:
    env = _env(max_output_tokens=100)
    for body in (
        {**BODY, "banana": 1},
        {"messages": [{"role": "user", "content": "x", "name": "y"}]},
        {**BODY, "max_tokens": 101},
    ):
        response = env.post(body)
        assert (response.status_code, response.json()["code"]) == (400, "bad_request"), body
    assert env.post({**BODY, "temperature": 2}).status_code == 422
    assert env.post({"messages": []}).status_code == 422


def test_prompt_too_large_413() -> None:
    env = _env(max_prompt_tokens=10)
    response = env.post({"messages": [{"role": "user", "content": "palavra " * 100}]})
    assert response.status_code == 413 and response.json()["code"] == "prompt_too_large"
    event = env.usage.events[-1]
    assert (event.status, event.error_code, event.tokens_out) == ("rejected", "prompt_too_large", 0)


def test_model_not_allowed_and_not_configured_and_unauthenticated() -> None:
    env = _env()
    denied = env.post({**BODY, "model": "outro"})
    assert (denied.status_code, denied.json()["subcode"]) == (403, "model_not_allowed")
    anonymous = env.client.post("/v1/chat/completions", json=BODY)
    assert anonymous.status_code == 401
    bare = TestClient(create_app(Settings.for_tests(), GatewayDeps(authenticator=None)))
    assert bare.post("/v1/chat/completions", json=BODY).status_code == 401


def test_fallback_and_all_models_failed() -> None:
    policy = TenantPolicy(tenant_id="t1", allowed_models=("primary", "secondary"))
    env = Env(
        {"primary": Failing(), "secondary": FakeLLMProvider("scripted", responses=["ok"] * 5)},
        policy,
    )
    response = env.post(BODY)
    assert response.status_code == 200 and response.headers["x-model-alias"] == "secondary"
    streamed = env.post({**BODY, "stream": True})
    assert streamed.headers["x-model-alias"] == "secondary" and "ok" in streamed.text
    dead = Env({"primary": Failing(), "secondary": Failing()}, policy)
    for body in (BODY, {**BODY, "stream": True}):
        failed = dead.post(body)
        assert (failed.status_code, failed.json()["subcode"]) == (502, "all_models_failed")
    assert dead.usage.events[-1].status == "error"


def test_inv03_gateway_logs_have_no_content(captured_logs: list[dict[str, Any]]) -> None:
    env = _env(f"resposta com {CANARY}")
    body = {"messages": [{"role": "user", "content": f"pergunta com {CANARY}"}]}
    assert env.post(body).status_code == 200
    assert env.post({**body, "stream": True}).status_code == 200
    assert env.post({**body, "tools": [CANARY]}).status_code == 400
    assert env.post({**body, CANARY: 1}).status_code == 400
    dumped = json.dumps(captured_logs, default=str) + repr(env.usage.events)
    assert CANARY not in dumped
    assert any(e.get("event") == "chat_completion" for e in captured_logs)


def test_usage_recorded_and_quota_decremented() -> None:
    env = _env("x" * 400, monthly_token_quota=400, max_output_tokens=300)
    first = env.post(BODY)
    assert first.status_code == 200
    used = env.usage.tokens_used_this_month("t1")
    assert used == first.json()["usage"]["total_tokens"] > 100
    event = env.usage.events[0]
    assert (event.tenant_id, event.user_id, event.model, event.status) == (
        "t1",
        "u1",
        "primary",
        "ok",
    )
    second = env.post(BODY)  # 300 pedidos de saída + prompt já não cabem na quota restante
    assert (second.status_code, second.json()["code"]) == (429, "quota_exceeded")
    assert env.usage.events[-1].status == "rejected"
    assert env.usage.tokens_used_this_month("t1") == used  # recusados não consomem


def test_upstream_stream_interrupted_emits_error_event_and_records_error() -> None:
    policy = TenantPolicy(tenant_id="t1", allowed_models=("primary", "secondary"))
    env = Env(
        {
            "primary": Interrupted("scripted", responses=[]),
            "secondary": FakeLLMProvider("scripted", responses=["x"]),
        },
        policy,
    )
    response = env.post({**BODY, "stream": True})
    assert response.status_code == 200  # os cabeçalhos já tinham saído
    events = _sse(response)
    assert events[-1].startswith("event: error")
    error = json.loads(events[-1].split("data: ", 1)[1])["error"]
    assert error["code"] == "upstream_error" and set(error) == {"code", "request_id"}
    assert "[DONE]" not in response.text
    event = env.usage.events[-1]
    assert (event.status, event.error_code) == ("error", "upstream_error")
    assert event.tokens_out > 0 and event.model == "primary"
