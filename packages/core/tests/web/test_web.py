"""Testes das peças HTTP partilhadas (``rag_core.web``)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from pydantic import BaseModel
from rag_core import errors
from rag_core.testing import assert_no_canary
from rag_core.web import (
    BodyLimitMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
    current_request_id,
    install_standard_web,
)
from starlette.testclient import TestClient

CANARY = "CANARIO-erro-interno-9Z"
# O TestClient usa um par de sockets internos (loopback); nada sai da máquina.
pytestmark = pytest.mark.enable_socket


class Item(BaseModel):
    name: str


def _app(max_body: int = 1024) -> FastAPI:
    app = FastAPI()
    install_standard_web(app, max_body)

    @app.get("/ok")
    def ok() -> dict[str, str | None]:
        return {"request_id": current_request_id()}

    @app.post("/items")
    def create(item: Item) -> dict[str, str]:
        return {"name": item.name}

    @app.post("/echo-size")
    async def echo_size(request: Any) -> dict[str, int]:
        return {"size": len(await request.body())}

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError(CANARY)

    @app.get("/rag/{code}")
    def rag(code: str) -> None:
        classes = {
            "validation": errors.ValidationFailed(subcode="zip_bomb"),
            "forbidden": errors.AccessDenied(),
            "missing": errors.NotFound(),
            "limit": errors.RateLimited(),
            "quota": errors.QuotaExceeded(),
            "upstream": errors.UpstreamError("http_500"),
            "big": errors.FileTooLarge(),
            "type": errors.UnsupportedType(),
            "sandbox": errors.SandboxViolation(),
        }
        raise classes[code]

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_app(), raise_server_exceptions=False)


def test_request_id_propagated_or_generated(client: TestClient) -> None:
    supplied = str(uuid.uuid4())
    response = client.get("/ok", headers={"X-Request-Id": supplied})
    assert response.headers["x-request-id"] == supplied
    assert response.json() == {"request_id": supplied}

    for bad in ("nao-e-uuid", "", "1" * 200, "<script>"):
        generated = client.get("/ok", headers={"X-Request-Id": bad})
        value = generated.headers["x-request-id"]
        assert uuid.UUID(value) and value != bad
        assert generated.json()["request_id"] == value
    assert client.get("/ok").headers["x-request-id"] != client.get("/ok").headers["x-request-id"]
    assert current_request_id() is None  # fora de um pedido


def test_security_headers_on_every_response(client: TestClient) -> None:
    for response in (client.get("/ok"), client.get("/nada"), client.get("/boom")):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cache-control"] == "no-store"


def test_body_too_large_413_problem_json(client: TestClient) -> None:
    response = client.post("/items", content=b"x" * 2000, headers={"Content-Type": "text/plain"})
    assert response.status_code == 413
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "file_too_large" and body["status"] == 413
    assert uuid.UUID(body["request_id"])
    assert response.headers["x-request-id"] == body["request_id"]
    assert client.post("/items", json={"name": "ok"}).status_code == 200  # abaixo do limite


def test_body_limit_counts_chunked_bodies() -> None:
    def chunks() -> Any:
        for _ in range(5):
            yield b"x" * 400

    client = TestClient(_app(max_body=1024), raise_server_exceptions=False)
    response = client.post("/items", content=chunks(), headers={"Content-Type": "text/plain"})
    assert response.status_code == 413  # sem Content-Length: contou os bytes
    assert response.json()["code"] == "file_too_large"


def test_inv03_unhandled_error_returns_generic_problem(
    client: TestClient, captured_logs: list[dict[str, Any]]
) -> None:
    response = client.get("/boom")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "internal_error"
    assert_no_canary(response.text, str(captured_logs))
    events = [e for e in captured_logs if e["event"] == "unhandled_error"]
    assert len(events) == 1 and events[0]["exc_type"] == "RuntimeError"


@pytest.mark.parametrize(
    ("path", "status", "code", "subcode"),
    [
        ("validation", 422, "validation_failed", "zip_bomb"),
        ("forbidden", 403, "access_denied", None),
        ("missing", 404, "not_found", None),
        ("limit", 429, "rate_limited", None),
        ("quota", 429, "quota_exceeded", None),
        ("upstream", 502, "upstream_error", None),
        ("big", 413, "file_too_large", None),
        ("type", 415, "unsupported_type", None),
        ("sandbox", 500, "sandbox_violation", None),
    ],
)
def test_rag_errors_map_to_problem_json(
    client: TestClient, path: str, status: int, code: str, subcode: str | None
) -> None:
    response = client.get(f"/rag/{path}")
    body = response.json()
    assert (response.status_code, body["code"], body.get("subcode")) == (status, code, subcode)
    assert body["type"] == f"urn:rag:error:{code}" and body["status"] == status
    assert set(body) <= {"type", "title", "status", "code", "subcode", "request_id"}
    assert response.headers["content-type"].startswith("application/problem+json")


def test_framework_errors_are_problem_json_without_echoing_input(client: TestClient) -> None:
    missing = client.get("/nao-existe")
    assert (missing.status_code, missing.json()["code"]) == (404, "not_found")
    wrong_method = client.delete("/ok")
    assert (wrong_method.status_code, wrong_method.json()["code"]) == (405, "method_not_allowed")
    marker = "CANARIO-corpo-invalido"
    invalid = client.post("/items", json={"name": 123, "extra": marker})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "validation_failed"
    assert invalid.json()["subcode"] == "invalid_request"
    assert marker not in invalid.text
    wrong_type = client.post("/items", json={"nome": marker})
    assert marker not in wrong_type.text


def test_non_http_scopes_pass_through() -> None:
    import asyncio

    seen: list[str] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        seen.append(scope["type"])

    async def run() -> None:
        for middleware in (RequestIdMiddleware, SecurityHeadersMiddleware, BodyLimitMiddleware):
            await middleware(inner)({"type": "lifespan"}, None, None)  # type: ignore[arg-type]

    asyncio.run(run())
    assert seen == ["lifespan"] * 3


def test_asgi_edge_cases_disconnect_and_error_after_response_started() -> None:
    import asyncio

    from rag_core.web import UnhandledErrorMiddleware

    sent: list[str] = []

    async def collect(message: Any) -> None:
        sent.append(message["type"])

    async def app_reads_body(scope: Any, receive: Any, send: Any) -> None:
        sent.append((await receive())["type"])

    async def disconnected() -> Any:
        return {"type": "http.disconnect"}

    async def partial_then_boom(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("depois de começar a responder")

    async def run() -> None:
        scope = {"type": "http", "headers": []}
        await BodyLimitMiddleware(app_reads_body, 10)(scope, disconnected, collect)
        with pytest.raises(RuntimeError):  # a resposta já saiu em parte: não se substitui
            await UnhandledErrorMiddleware(partial_then_boom)(scope, disconnected, collect)
        await UnhandledErrorMiddleware(app_reads_body)({"type": "lifespan"}, disconnected, collect)

    asyncio.run(run())
    assert sent == ["http.disconnect", "http.response.start", "http.disconnect"]
