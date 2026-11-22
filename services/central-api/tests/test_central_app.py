"""Testes de F8-T01: esqueleto da Central API (healthz, readyz, JWKS, sem CORS, OpenAPI)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from rag_central.app import CentralDeps, create_app
from rag_central.export_openapi import OPENAPI_PATH, build_openapi, render
from rag_central.signing import Signer, generate_keys_json, load_keys
from rag_core.clock import SystemClock
from rag_core.config import Settings

pytestmark = pytest.mark.enable_socket


def _client(**readiness: object) -> TestClient:
    deps = CentralDeps(readiness=readiness)  # type: ignore[arg-type]
    return TestClient(create_app(Settings.for_tests(), deps), raise_server_exceptions=False)


def test_healthz_readyz() -> None:
    assert _client().get("/healthz").json() == {"status": "ok"}
    assert _client().get("/readyz").json() == {"status": "ready", "checks": {}}
    ready = _client(database=lambda: True).get("/readyz")
    assert ready.status_code == 200 and ready.json()["checks"] == {"database": True}

    def boom() -> bool:
        raise RuntimeError("postgresql://u:SEGREDO@h/db")

    down = _client(database=boom).get("/readyz")
    assert down.status_code == 503 and down.json()["checks"] == {"database": False}
    assert "SEGREDO" not in down.text


def test_jwks_endpoint_serves_public_keys_only() -> None:
    signer = Signer(load_keys(SecretStr(generate_keys_json("k1"))), "https://c.test", SystemClock())
    client = TestClient(create_app(Settings.for_tests(), CentralDeps(signer=signer)))
    response = client.get("/.well-known/jwks.json")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"
    assert [k["kid"] for k in response.json()["keys"]] == ["k1"]
    assert all("d" not in k for k in response.json()["keys"])
    assert _client().get("/.well-known/jwks.json").json() == {"keys": []}  # sem chaves configuradas


def test_no_cors_headers_for_foreign_origin() -> None:
    client = _client()
    response = client.get("/healthz", headers={"Origin": "https://evil.example"})
    assert not any(name.lower().startswith("access-control-") for name in response.headers)
    preflight = client.options(
        "/healthz",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert preflight.status_code == 405
    assert not any(name.lower().startswith("access-control-") for name in preflight.headers)
    assert response.headers["x-request-id"] and "x-content-type-options" in response.headers


def test_unknown_routes_are_problem_json() -> None:
    client = _client()
    missing = client.get("/v1/nao-existe")
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"
    assert client.get("/internal/v1/nao-existe").status_code == 404
    assert client.get("/backoffice/v1/nao-existe").status_code == 404


def test_openapi_snapshot_matches() -> None:
    committed = OPENAPI_PATH.read_text(encoding="utf-8")
    assert committed == render(build_openapi()), (
        "o openapi.json mudou: corre `make openapi` e faz commit do resultado"
    )
    paths = sorted(build_openapi()["paths"])
    assert paths[:3] == [
        "/.well-known/jwks.json",
        "/healthz",
        "/internal/v1/devices/{device_id}/status",
    ]
    assert "/internal/v1/usage" in paths and "/internal/v1/principals/resolve" in paths
