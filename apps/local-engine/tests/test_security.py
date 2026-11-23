"""Testes de F11-T01: Host, Origin e token do servidor local (INV-11)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from rag_local.app import create_app

pytestmark = pytest.mark.enable_socket
TOKEN = "token-de-teste-0123456789"
PORT = 49152


def _client(dev: bool = False) -> TestClient:
    app = create_app(token=TOKEN, port=PORT, dev=dev)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}")


def _auth(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_inv11_missing_or_wrong_token_401() -> None:
    client = _client()
    for headers in (
        {},
        _auth("errado"),
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": "Bearer"},
        {"Authorization": f"Bearer {TOKEN}x"},
    ):
        response = client.get("/v1/health", headers=headers)
        assert response.status_code == 401, headers
        assert response.json() == {"code": "unauthenticated"}
        assert TOKEN not in response.text
    assert client.get("/v1/health", headers=_auth()).json()["status"] == "ok"


def test_inv11_dns_rebinding_host_rejected() -> None:
    client = _client()
    for host in (f"evil.example:{PORT}", "127.0.0.1", f"127.0.0.1:{PORT + 1}", "evil.example"):
        response = client.get("/v1/health", headers={**_auth(), "Host": host})
        assert response.status_code == 421, host
    for host in (f"127.0.0.1:{PORT}", f"localhost:{PORT}"):
        assert client.get("/v1/health", headers={**_auth(), "Host": host}).status_code == 200


def test_inv11_foreign_origin_403() -> None:
    client = _client()
    for origin in ("https://evil.example", "http://localhost:1420", "null"):
        response = client.get("/v1/health", headers={**_auth(), "Origin": origin})
        assert response.status_code == 403, origin
        assert "access-control-allow-origin" not in response.headers


def test_allowed_origin_with_token_200() -> None:
    client = _client()
    for origin in ("tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"):
        response = client.get("/v1/health", headers={**_auth(), "Origin": origin})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
    assert client.get("/v1/health", headers=_auth()).status_code == 200  # sem Origin (curl)
    dev = _client(dev=True).get(
        "/v1/health", headers={**_auth(), "Origin": "http://localhost:1420"}
    )
    assert dev.status_code == 200


def test_preflight_needs_no_token_but_only_for_allowed_origins() -> None:
    client = _client()
    ok = client.options(
        "/v1/health",
        headers={"Origin": "tauri://localhost", "Access-Control-Request-Method": "GET"},
    )
    assert ok.status_code == 204 and "authorization" in ok.headers["access-control-allow-headers"]
    bad = client.options("/v1/health", headers={"Origin": "https://evil.example"})
    assert bad.status_code == 403
    assert client.options("/v1/health").status_code == 401  # sem Origin é um pedido normal
    assert client.options("/v1/health", headers={"Host": "evil.example"}).status_code == 421


def test_unauthenticated_responses_have_cors_only_for_allowed_origins() -> None:
    response = _client().get("/v1/health", headers={"Origin": "tauri://localhost"})
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "tauri://localhost"
