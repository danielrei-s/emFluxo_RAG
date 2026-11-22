"""Testes de F6-T01: esqueleto do gateway (middlewares comuns, healthz, readyz, erros)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from rag_core.config import Settings
from rag_core.testing import assert_no_canary
from rag_gateway.app import GatewayDeps, create_app
from rag_gateway.middleware import MAX_BODY_BYTES

# O TestClient usa um par de sockets internos (loopback); nada sai da máquina.
pytestmark = pytest.mark.enable_socket
CANARY = "CANARIO-erro-do-gateway-3K"


def _client(deps: GatewayDeps | None = None) -> TestClient:
    return TestClient(create_app(Settings.for_tests(), deps), raise_server_exceptions=False)


def test_healthz() -> None:
    response = _client().get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"


def test_readyz_reports_each_dependency() -> None:
    ready = _client(GatewayDeps(readiness={"db": lambda: True, "modelos": lambda: True}))
    assert ready.get("/readyz").json() == {
        "status": "ready",
        "checks": {"db": True, "modelos": True},
    }

    def broken() -> bool:
        raise RuntimeError(CANARY)

    down = _client(
        GatewayDeps(readiness={"db": lambda: True, "modelos": broken, "x": lambda: False})
    )
    response = down.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"db": True, "modelos": False, "x": False},
    }
    assert CANARY not in response.text  # o erro da verificação não sai
    assert _client().get("/readyz").json() == {"status": "ready", "checks": {}}  # sem dependências


def test_request_id_propagated_or_generated() -> None:
    client = _client()
    supplied = str(uuid.uuid4())
    assert (
        client.get("/healthz", headers={"X-Request-Id": supplied}).headers["x-request-id"]
        == supplied
    )
    generated = client.get("/healthz", headers={"X-Request-Id": "nao-e-uuid"}).headers
    assert uuid.UUID(generated["x-request-id"])


def test_body_too_large_413_problem_json() -> None:
    response = _client().post("/healthz", content=b"x" * (MAX_BODY_BYTES + 1))
    assert response.status_code == 413
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "file_too_large" and body["status"] == 413
    assert body["request_id"] == response.headers["x-request-id"]
    assert MAX_BODY_BYTES == 256 * 1024


def test_unknown_routes_and_methods_are_problem_json() -> None:
    client = _client()
    missing = client.get("/nao-existe")
    assert (missing.status_code, missing.json()["code"]) == (404, "not_found")
    wrong = client.post("/healthz")
    assert (wrong.status_code, wrong.json()["code"]) == (405, "method_not_allowed")
    assert wrong.headers["x-content-type-options"] == "nosniff"
    assert wrong.headers["referrer-policy"] == "no-referrer"


def test_no_public_documentation_endpoints() -> None:
    client = _client()
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_inv03_unhandled_error_returns_generic_problem(
    caplog: pytest.LogCaptureFixture, captured_logs: list[dict[str, Any]]
) -> None:
    app = create_app(Settings.for_tests())

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError(CANARY)

    caplog.set_level(logging.DEBUG)
    response = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error" and body["status"] == 500
    assert response.headers["x-request-id"] == body["request_id"]
    assert response.headers["cache-control"] == "no-store"
    assert_no_canary(response.text, str(captured_logs), caplog.text)
    assert [e["exc_type"] for e in captured_logs if e["event"] == "unhandled_error"] == [
        "RuntimeError"
    ]
