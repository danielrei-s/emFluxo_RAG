"""Testes de F8-T04: cliente do gateway (tokens de serviço, streaming e erros)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import jwt as pyjwt
import pytest
from pydantic import SecretStr
from rag_central.gateway_client import GatewayLLMClient, RetryableRateLimited
from rag_central.signing import Signer, generate_keys_json, load_keys
from rag_core.clock import SystemClock
from rag_core.errors import (
    AccessDenied,
    BadRequest,
    PromptTooLarge,
    QuotaExceeded,
    UnsupportedFeature,
    UpstreamError,
)
from rag_core.types import ChatMessage, GenerationParams, Principal, Role

PRINCIPAL = Principal(tenant_id="t1", user_id="u1", role=Role.MEMBER)
MESSAGES = [ChatMessage(role="user", content="CANARIO pergunta")]
PARAMS = GenerationParams(max_tokens=50, temperature=0.2)
SIGNER = Signer(load_keys(SecretStr(generate_keys_json("k1"))), "https://c.test", SystemClock())


def _client(handler: Any, **kwargs: Any) -> GatewayLLMClient:
    return GatewayLLMClient(
        "https://gw.test/", SIGNER, PRINCIPAL, transport=httpx.MockTransport(handler), **kwargs
    )


def _problem(status: int, code: str, sub: str | None = None, **headers: str) -> httpx.Response:
    body = {"code": code, **({"subcode": sub} if sub else {})}
    return httpx.Response(status, json=body, headers=headers)


def _sse(*events: str) -> httpx.Response:
    return httpx.Response(200, text="\n\n".join(events) + "\n\n")


def _chunk(text: str) -> str:
    return "data: " + json.dumps({"choices": [{"delta": {"content": text}}]})


def test_token_claims_and_ttl() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "olá"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            },
            headers={"x-model-alias": "rag-default"},
        )

    client = _client(handler, model="rag-default")
    result = client.generate(MESSAGES, params=PARAMS)
    client.generate(MESSAGES, params=PARAMS)
    assert (result.text, result.model, result.tokens_in, result.tokens_out) == (
        "olá", "rag-default", 7, 3,
    )  # fmt: skip
    request = seen[0]
    assert str(request.url) == "https://gw.test/v1/chat/completions"
    token = request.headers["authorization"].removeprefix("Bearer ")
    claims = pyjwt.decode(token, options={"verify_signature": False})
    assert (claims["typ"], claims["tenant_id"], claims["user_id"], claims["purpose"]) == (
        "service", "t1", "u1", "chat",
    )  # fmt: skip
    assert claims["exp"] - claims["iat"] == 60 and claims["aud"] == "rag-gateway"
    body = json.loads(request.content)
    assert body["model"] == "rag-default" and body["stream"] is False and body["max_tokens"] == 50
    assert client.is_remote is True and "CANARIO" not in repr(client)


def test_a_fresh_token_is_minted_for_each_request() -> None:
    tokens: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        tokens.append(request.headers["authorization"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    client = _client(handler)
    for _ in range(2):
        client.generate(MESSAGES, params=PARAMS)
    assert len(tokens) == 2 and tokens[0] != tokens[1]  # jti distinto em cada pedido
    client.close()


def test_stream_passthrough() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        role = "data: " + json.dumps({"choices": [{"delta": {"role": "assistant"}}]})
        return _sse(role, _chunk("uma "), _chunk("resposta"), "data: [DONE]")

    assert "".join(_client(handler).stream(MESSAGES, params=PARAMS)) == "uma resposta"


def test_stream_error_event_and_garbage() -> None:
    def interrupted(request: httpx.Request) -> httpx.Response:
        return _sse(_chunk("parcial "), 'event: error\ndata: {"error": {"code": "upstream_error"}}')

    stream = _client(interrupted).stream(MESSAGES, params=PARAMS)
    assert next(stream) == "parcial "
    with pytest.raises(UpstreamError, match="stream_interrupted"):
        next(stream)
    with pytest.raises(UpstreamError, match="invalid_stream"):
        list(_client(lambda r: _sse("data: não-json")).stream(MESSAGES, params=PARAMS))


def test_error_mapping() -> None:
    cases: list[tuple[httpx.Response, type[Exception]]] = [
        (_problem(429, "rate_limited", "user_rate", **{"Retry-After": "12"}), RetryableRateLimited),
        (_problem(429, "quota_exceeded", "monthly_quota"), QuotaExceeded),
        (_problem(400, "unsupported_feature", "tools"), UnsupportedFeature),
        (_problem(400, "bad_request", "unknown_field"), BadRequest),
        (_problem(413, "prompt_too_large"), PromptTooLarge),
        (_problem(403, "access_denied", "model_not_allowed"), AccessDenied),
        (_problem(401, "unauthenticated"), UpstreamError),
        (_problem(502, "upstream_error", "all_models_failed"), UpstreamError),
        (httpx.Response(500, text="<html>CANARIO</html>"), UpstreamError),
    ]
    for response, expected in cases:
        for call in ("generate", "stream"):
            client = _client(lambda r, resp=response: resp)  # type: ignore[misc]
            with pytest.raises(expected) as exc:
                if call == "generate":
                    client.generate(MESSAGES, params=PARAMS)
                else:
                    list(client.stream(MESSAGES, params=PARAMS))
            assert "CANARIO" not in str(exc.value)
    limited = _client(lambda r: _problem(429, "rate_limited", "user_rate", **{"Retry-After": "12"}))
    with pytest.raises(RetryableRateLimited) as retry:
        limited.generate(MESSAGES, params=PARAMS)
    assert retry.value.retry_after_s == 12 and retry.value.detail_id == "user_rate"
    no_header = _client(lambda r: _problem(429, "rate_limited"))
    with pytest.raises(RetryableRateLimited) as fallback:
        no_header.generate(MESSAGES, params=PARAMS)
    assert fallback.value.retry_after_s == 60


def test_network_failures_and_bad_bodies_are_upstream_errors() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lento", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("recusado", request=request)

    with pytest.raises(UpstreamError, match="timeout"):
        _client(timeout).generate(MESSAGES, params=PARAMS)
    with pytest.raises(UpstreamError, match="connection"):
        _client(refused).generate(MESSAGES, params=PARAMS)
    with pytest.raises(UpstreamError, match="invalid_response"):
        _client(lambda r: httpx.Response(200, json={"choices": []})).generate(
            MESSAGES, params=PARAMS
        )
