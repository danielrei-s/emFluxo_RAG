"""Testes de F8-T07 (integração): dispositivos, licença e revogação (INV-14, INV-19)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx
import psycopg
import pytest
from conftest import TENANT_A, TENANT_B, USER_1, USER_2, USER_3, Rls
from fastapi import Depends
from fastapi.testclient import TestClient
from pydantic import SecretStr
from rag_central.app import CentralDeps, create_app
from rag_central.auth import CentralAuth, PrincipalResolver, build_identity_verifier
from rag_central.db import Database, make_pool
from rag_central.routers.devices import require_active_device
from rag_central.signing import Signer, generate_keys_json, load_keys
from rag_core.auth import JwksVerifier
from rag_core.clock import SystemClock
from rag_core.config import Settings
from rag_core.testing.jwt import JwtFactory
from rag_core.types import Principal

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
ISSUER = "https://supabase.test/auth/v1"


@dataclass
class Env:
    client: TestClient
    factory: JwtFactory
    signer: Signer
    rls: Rls

    def call(
        self,
        method: str,
        path: str,
        sub: str,
        tenant: str | None = None,
        device: str | None = None,
        aal: str = "aal1",
        **kwargs: Any,
    ) -> httpx.Response:
        token = self.factory.issue(self.factory.claims(sub=sub, aal=aal))
        headers = {"Authorization": f"Bearer {token}"}
        if tenant:
            headers["X-Tenant-Id"] = tenant
        if device:
            headers["X-Device-Id"] = device
        response: httpx.Response = self.client.request(method, path, headers=headers, **kwargs)
        return response

    def admin(self, statement: str) -> None:
        with psycopg.connect(self.rls.admin_dsn, autocommit=True) as conn:
            conn.execute(statement.encode())  # type: ignore[arg-type]

    def register(self, sub: str = USER_2, tenant: str = TENANT_B) -> str:
        response = self.call("POST", "/v1/devices/register", sub, tenant, json={"name": "PC"})
        assert response.status_code == 201, response.text
        return str(response.json()["id"])


@pytest.fixture
def env(rls: Rls) -> Iterator[Env]:
    factory = JwtFactory(issuer=ISSUER, audience="authenticated")
    http = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=factory.jwks()))
    )
    settings = Settings.for_tests(supabase_jwt_issuer=ISSUER, supabase_jwks_url="https://s.test/j")
    pool = make_pool(rls.dsn_for("app_api"), max_size=4)
    pool.open(wait=True)
    db = Database(pool)
    signer = Signer(load_keys(SecretStr(generate_keys_json("k1"))), "https://c.test", SystemClock())
    verifier = build_identity_verifier(settings, http)
    auth = CentralAuth(verifier, PrincipalResolver(db, SystemClock()))
    app = create_app(settings, CentralDeps(signer=signer, auth=auth, db=db))

    @app.get("/v1/search-probe")
    def probe(_: Principal = Depends(require_active_device)) -> dict[str, str]:  # noqa: B008
        return {"ok": "sim"}

    yield Env(TestClient(app, raise_server_exceptions=False), factory, signer, rls)
    pool.close()


def test_inv19_register_requires_local_product(env: Env) -> None:
    denied = env.call("POST", "/v1/devices/register", USER_1, json={"name": "PC"})  # A: só web
    assert (denied.status_code, denied.json()["subcode"]) == (403, "product_not_entitled")
    assert env.register()  # o tenant B tem o produto local
    for bad in ({}, {"name": ""}, {"name": "x", "extra": 1}):
        assert env.call("POST", "/v1/devices/register", USER_2, json=bad).status_code == 422


def test_entitlement_token_verifiable_and_contentless(env: Env) -> None:
    device = env.register()
    response = env.call("GET", "/v1/devices/me", USER_2, device=device)
    body = response.json()
    assert response.status_code == 200 and body["status"] == "active"
    assert set(body["policy"]) == {
        "forced_offline", "block_cloud_for", "allowed_folders", "wipe_on_revoke",
    }  # fmt: skip
    http = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=env.signer.jwks()))
    )
    verifier = JwksVerifier("https://c.test/jwks", "https://c.test", "rag-local", http=http)
    claims = verifier.verify(body["entitlement_token"])
    assert (claims["sub"], claims["tenant_id"], claims["device_id"]) == (USER_2, TENANT_B, device)
    assert claims["products"] == ["local", "web"] and claims["typ"] == "entitlement"
    with psycopg.connect(env.rls.admin_dsn) as conn:
        seen = conn.execute("select last_seen_at is not null from app.devices").fetchone()
    assert seen == (True,)


def test_revoke_then_heartbeat_reports_revoked_and_search_403(env: Env) -> None:
    device = env.register()
    assert env.call("GET", "/v1/search-probe", USER_2, device=device).status_code == 200
    assert env.call("POST", f"/v1/devices/{device}/revoke", USER_2).status_code == 200
    heartbeat = env.call("GET", "/v1/devices/me", USER_2, device=device).json()
    assert heartbeat["status"] == "revoked" and heartbeat["entitlement_token"] is None
    blocked = env.call("GET", "/v1/search-probe", USER_2, device=device)
    assert (blocked.status_code, blocked.json()["subcode"]) == (403, "device_revoked")
    assert env.call("GET", "/v1/search-probe", USER_2).status_code == 200  # sem cabeçalho: web
    with psycopg.connect(env.rls.admin_dsn) as conn:
        actions = conn.execute("select action from app.audit_log order by id").fetchall()
    assert actions == [("device.register",), ("device.revoke",)]


def test_member_cannot_revoke_others_device(env: Env) -> None:
    device = env.register(USER_2)
    env.admin(
        "update app.memberships set role = 'admin' "
        f"where user_id = '{USER_3}' and tenant_id = '{TENANT_B}'"
    )
    # a U3 passa a admin, mas só com aal1: vê e revoga apenas o que é seu (a pertença está em cache)
    assert env.call("POST", f"/v1/devices/{device}/revoke", USER_3, TENANT_B).status_code == 404
    assert env.call("GET", "/v1/devices", USER_3, TENANT_B).status_code == 403  # admin, mas aal1
    listing = env.call("GET", "/v1/devices", USER_3, TENANT_B, aal="aal2")
    assert [d["id"] for d in listing.json()] == [device]
    revoke = env.call("POST", f"/v1/devices/{device}/revoke", USER_3, TENANT_B, aal="aal2")
    assert revoke.status_code == 200


def test_device_of_other_user_rejected(env: Env) -> None:
    device = env.register(USER_2)
    stolen = env.call("GET", "/v1/devices/me", USER_3, TENANT_B, device=device)
    assert stolen.status_code == 404  # o dispositivo do U2 não é do U3
    probe = env.call("GET", "/v1/search-probe", USER_3, TENANT_B, device=device)
    assert (probe.status_code, probe.json()["subcode"]) == (403, "unknown_device")
    assert env.call("GET", "/v1/devices/me", USER_2, device="nao-e-uuid").status_code == 422
    assert env.call("GET", "/v1/devices/me", USER_2).status_code == 422  # sem cabeçalho
    assert TENANT_A != TENANT_B
