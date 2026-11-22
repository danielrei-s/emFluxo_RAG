"""Testes de F8-T06 (integração): endpoints internos para o gateway."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import psycopg
import pytest
from conftest import TENANT_A, TENANT_B, USER_1, USER_2, USER_3, Rls
from fastapi.testclient import TestClient
from pydantic import SecretStr
from rag_central.app import CentralDeps, create_app
from rag_central.auth import CentralAuth, PrincipalResolver
from rag_central.db import Database, make_pool
from rag_core.clock import FakeClock
from rag_core.config import Settings

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
KEY = "chave-interna-de-teste"
DEVICE_A = "dddddddd-0000-4000-8000-0000000000a1"


@dataclass
class Env:
    client: TestClient
    rls: Rls

    def call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"X-Internal-Key": KEY, **kwargs.pop("headers", {})}
        response: httpx.Response = self.client.request(
            method, f"/internal/v1{path}", headers=headers, **kwargs
        )
        return response

    def admin(self, statement: str, *params: Any) -> None:
        with psycopg.connect(self.rls.admin_dsn, autocommit=True) as conn:
            conn.execute(statement.encode(), params)  # type: ignore[arg-type]


@pytest.fixture
def env(rls: Rls) -> Iterator[Env]:
    pool = make_pool(rls.dsn_for("app_api"), max_size=4)
    pool.open(wait=True)
    db = Database(pool)
    clock = FakeClock(datetime(2026, 5, 10, tzinfo=UTC))
    auth = CentralAuth(verifier=None, resolver=PrincipalResolver(db, clock))  # type: ignore[arg-type]
    settings = Settings.for_tests(internal_api_key=SecretStr(KEY))
    app = create_app(settings, CentralDeps(auth=auth, db=db))
    yield Env(TestClient(app, raise_server_exceptions=False), rls)
    pool.close()


def test_internal_key_required(env: Env) -> None:
    for headers in ({}, {"X-Internal-Key": "errada"}, {"X-Internal-Key": ""}):
        response = env.client.get(f"/internal/v1/tenants/{TENANT_A}/policy", headers=headers)
        assert response.status_code == 401 and response.json()["code"] == "unauthenticated"
    assert env.call("GET", f"/tenants/{TENANT_A}/policy").status_code == 200
    unconfigured = TestClient(create_app(Settings.for_tests()), raise_server_exceptions=False)
    r = unconfigured.get(f"/internal/v1/tenants/{TENANT_A}/policy", headers={"X-Internal-Key": KEY})
    assert (r.status_code, r.json()["subcode"]) == (401, "internal_api_not_configured")


def test_internal_api_not_reachable_via_edge_headers(env: Env) -> None:
    for header in ("Cf-Connecting-Ip", "Cf-Ray"):
        response = env.call("GET", f"/tenants/{TENANT_A}/policy", headers={header: "1.2.3.4"})
        assert response.status_code == 404  # mesmo com a chave certa
    assert (
        env.call("POST", "/usage", json={"events": []}, headers={"Cf-Ray": "x"}).status_code == 404
    )


def test_policy_mapping_defaults(env: Env) -> None:
    default = env.call("GET", f"/tenants/{TENANT_A}/policy").json()
    assert default["tenant_id"] == TENANT_A and default["status"] == "active"
    assert default["products"] == ["web"]  # vem da coluna, não das settings
    assert default["monthly_token_quota"] == 2_000_000 and default["allowed_models"] == [
        "rag-default"
    ]
    env.admin(
        "update app.tenants set status = 'suspended', settings = %s::jsonb where id = %s",
        '{"policy": {"monthly_token_quota": 5000, "allowed_models": ["a", "b"], '
        '"status": "active", "products": ["local"], "tenant_id": "x", "desconhecido": 1}}',
        TENANT_A,
    )
    custom = env.call("GET", f"/tenants/{TENANT_A}/policy").json()
    assert (custom["monthly_token_quota"], custom["allowed_models"]) == (5000, ["a", "b"])
    assert (custom["status"], custom["products"], custom["tenant_id"]) == (
        "suspended", ["web"], TENANT_A,
    )  # as settings nunca mudam estado, produtos nem identidade  # fmt: skip
    env.admin(
        "update app.tenants set settings = %s::jsonb where id = %s",
        '{"policy": {"max_prompt_tokens": "muito"}}',
        TENANT_B,
    )
    broken = env.call("GET", f"/tenants/{TENANT_B}/policy")
    assert (broken.status_code, broken.json()["subcode"]) == (422, "invalid_policy")
    missing = env.call("GET", "/tenants/cccccccc-0000-4000-8000-0000000000cc/policy")
    assert missing.status_code == 404
    assert env.call("GET", "/tenants/nao-e-uuid/policy").status_code == 422


def _event(
    tenant: str, tokens_in: int = 10, tokens_out: int = 5, status: str = "ok"
) -> dict[str, Any]:
    return {
        "tenant_id": tenant, "user_id": USER_1, "device_id": None, "model": "rag-default",
        "tokens_in": tokens_in, "tokens_out": tokens_out, "latency_ms": 30, "ttft_ms": 10,
        "status": status, "error_code": None, "at": "2026-05-10T12:00:00+00:00",
    }  # fmt: skip


def test_usage_batch_persisted_without_content(env: Env) -> None:
    now = datetime.now(UTC).isoformat()
    events = [
        {**_event(TENANT_A, 100, 50), "at": now},
        {**_event(TENANT_A, 1, 1, "error"), "error_code": "upstream_error", "at": now},
        {**_event(TENANT_B, 7, 3), "at": now},
    ]
    response = env.call("POST", "/usage", json={"events": events})
    assert (response.status_code, response.json()) == (202, {"accepted": 3})
    with psycopg.connect(env.rls.admin_dsn) as conn:
        rows = conn.execute(
            "select tenant_id::text, tokens_in, status from app.usage_events order by id"
        ).fetchall()
        columns = {
            r[0] for r in conn.execute(
                "select column_name from information_schema.columns where table_name = 'usage_events'"
            ).fetchall()
        }  # fmt: skip
    assert rows == [(TENANT_A, 100, "ok"), (TENANT_A, 1, "error"), (TENANT_B, 7, "ok")]
    assert not columns & {"content", "text", "prompt", "answer", "message", "messages"}
    assert env.call("GET", f"/tenants/{TENANT_A}/usage/month").json() == {"tokens": 150}  # só ok
    assert env.call("GET", f"/tenants/{TENANT_B}/usage/month").json() == {"tokens": 10}


def test_usage_rejects_content_and_bad_values(env: Env) -> None:
    for bad in (
        {**_event(TENANT_A), "prompt": "CANARIO"},  # campo desconhecido
        {**_event(TENANT_A), "tokens_in": -1},
        {**_event(TENANT_A), "status": "talvez"},
        {**_event(TENANT_A), "error_code": "Erro com texto livre"},
        {**_event(TENANT_A), "model": "m" * 65},
    ):
        response = env.call("POST", "/usage", json={"events": [bad]})
        assert response.status_code == 422 and "CANARIO" not in response.text
    assert env.call("POST", "/usage", json={"events": [_event(TENANT_A)] * 501}).status_code == 422
    assert env.call("POST", "/usage", json={"events": [_event("nao-uuid")]}).status_code == 422
    with psycopg.connect(env.rls.admin_dsn) as conn:
        assert conn.execute("select count(*) from app.usage_events").fetchone() == (0,)


def test_device_status(env: Env) -> None:
    env.admin(
        "insert into app.devices (id, tenant_id, user_id, name) values (%s, %s, %s, 'pc')",
        DEVICE_A, TENANT_A, USER_1,
    )  # fmt: skip
    params = {"tenant_id": TENANT_A, "user_id": USER_1}
    assert env.call("GET", f"/devices/{DEVICE_A}/status", params=params).json() == {
        "status": "active"
    }
    env.admin("update app.devices set status = 'revoked' where id = %s", DEVICE_A)
    assert env.call("GET", f"/devices/{DEVICE_A}/status", params=params).json() == {
        "status": "revoked"
    }
    other_user = env.call(
        "GET", f"/devices/{DEVICE_A}/status", params={**params, "user_id": USER_3}
    )
    other_tenant = env.call(
        "GET", f"/devices/{DEVICE_A}/status", params={**params, "tenant_id": TENANT_B}
    )
    assert other_user.status_code == 404 and other_tenant.status_code == 404
    assert (
        env.call("GET", f"/devices/{DEVICE_A}/status").status_code == 422
    )  # tenant_id obrigatório


def test_principals_resolve(env: Env) -> None:
    body = env.call("POST", "/principals/resolve", json={"sub": USER_1}).json()
    assert (body["tenant_id"], body["role"], body["products"]) == (TENANT_A, "admin", ["web"])
    assert (
        env.call("POST", "/principals/resolve", json={"sub": USER_3}).status_code == 400
    )  # 2 tenants
    chosen = env.call("POST", "/principals/resolve", json={"sub": USER_3, "tenant_id": TENANT_B})
    assert chosen.json()["role"] == "editor"
    not_member = env.call(
        "POST", "/principals/resolve", json={"sub": USER_1, "tenant_id": TENANT_B}
    )
    assert not_member.status_code == 403
    # um dispositivo só existe no produto local: o tenant A só tem "web"
    no_local = env.call("POST", "/principals/resolve", json={"sub": USER_1, "device_id": DEVICE_A})
    assert (no_local.status_code, no_local.json()["subcode"]) == (403, "product_not_entitled")
    with_local = env.call(
        "POST", "/principals/resolve", json={"sub": USER_2, "device_id": DEVICE_A}
    )
    assert with_local.status_code == 200
    assert env.call("POST", "/principals/resolve", json={"sub": USER_1, "x": 1}).status_code == 422
