"""Testes de F8-T10 (integração): administração do tenant (INV-01, INV-14, INV-15)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx
import psycopg
import pytest
from conftest import TENANT_A, TENANT_B, USER_1, USER_2, USER_3, Rls
from fastapi.testclient import TestClient
from pydantic import SecretStr
from rag_central.app import CentralDeps, create_app
from rag_central.auth import CentralAuth, PrincipalResolver, build_identity_verifier
from rag_central.auth_admin import FakeAuthAdmin, SupabaseAuthAdmin
from rag_central.db import Database, make_pool
from rag_core.clock import SystemClock
from rag_core.config import Settings
from rag_core.errors import UpstreamError
from rag_core.testing.jwt import JwtFactory

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
ISSUER = "https://supabase.test/auth/v1"
GROUP_A = "11111111-0000-4000-8000-000000000001"


@dataclass
class Env:
    client: TestClient
    factory: JwtFactory
    auth_admin: FakeAuthAdmin
    rls: Rls

    def call(
        self, method: str, path: str, sub: str = USER_1, aal: str = "aal2", **kwargs: Any
    ) -> httpx.Response:
        token = self.factory.issue(self.factory.claims(sub=sub, aal=aal))
        response: httpx.Response = self.client.request(
            method, f"/v1/tenant{path}", headers={"Authorization": f"Bearer {token}"}, **kwargs
        )
        return response

    def admin(self, statement: str) -> None:
        with psycopg.connect(self.rls.admin_dsn, autocommit=True) as conn:
            conn.execute(statement.encode())  # type: ignore[arg-type]


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
    fake = FakeAuthAdmin()
    auth = CentralAuth(
        build_identity_verifier(settings, http), PrincipalResolver(db, SystemClock())
    )
    app = create_app(settings, CentralDeps(auth=auth, db=db, auth_admin=fake))
    yield Env(TestClient(app, raise_server_exceptions=False), factory, fake, rls)
    pool.close()


def test_inv15_requires_aal2(env: Env) -> None:
    for method, path in (
        ("GET", "/users"),
        ("GET", "/groups"),
        ("GET", "/settings"),
        ("GET", "/audit"),
    ):
        assert env.call(method, path, aal="aal1").status_code == 403, path
        assert env.call(method, path, aal="aal2").status_code == 200, path


def test_member_forbidden(env: Env) -> None:
    env.admin(f"update app.memberships set role = 'admin' where user_id = '{USER_1}'")
    for sub in (USER_2, USER_3):  # membro (tenant B) e editor com vários tenants → sem acesso
        response = env.call("GET", "/users", sub=sub)
        assert response.status_code in (400, 403), sub
    assert env.call("GET", "/users", sub=USER_2).status_code == 403


def test_admin_cannot_create_owner(env: Env) -> None:
    owner = env.call("POST", "/users", json={"email": "novo@x.test", "role": "owner"})
    assert owner.status_code == 422 and env.auth_admin.invites == []
    env.admin(
        f"update app.memberships set role = 'owner' where user_id = '{USER_3}' and tenant_id = '{TENANT_A}'"
    )
    env.admin(f"update app.memberships set role = 'admin' where user_id = '{USER_1}'")
    target = env.call("PATCH", f"/users/{USER_3}", json={"role": "member"})
    assert (target.status_code, target.json()["subcode"]) == (403, "cannot_modify_owner")
    promote = env.call("PATCH", f"/users/{USER_3}", json={"role": "owner"})
    assert promote.status_code == 422
    assert env.call("PATCH", f"/users/{USER_3}", json={}).status_code == 422
    assert env.call("PATCH", f"/users/{USER_2}", json={"role": "member"}).status_code == 404


def test_invite_calls_auth_admin(env: Env) -> None:
    response = env.call(
        "POST",
        "/users",
        json={"email": "novo@x.test", "role": "editor", "redirect_to": "https://a.test/ok"},
    )
    assert response.status_code == 201
    assert env.auth_admin.invites == [("novo@x.test", "https://a.test/ok")]
    listing = {u["email"]: u for u in env.call("GET", "/users").json()}
    assert (
        listing["novo@x.test"]["role"] == "editor" and listing["novo@x.test"]["status"] == "invited"
    )
    again = env.call("POST", "/users", json={"email": "novo@x.test"})
    assert (again.status_code, again.json()["subcode"]) == (422, "already_member")
    assert env.call("POST", "/users", json={"email": "sem-arroba"}).status_code == 422
    changed = env.call("PATCH", f"/users/{response.json()['user_id']}", json={"status": "disabled"})
    assert changed.status_code == 200
    audit = env.call("GET", "/audit").json()["items"]
    assert {e["action"] for e in audit} >= {"tenant.user_invite", "tenant.user_update"}


def test_groups_crud_and_members(env: Env) -> None:
    created = env.call("POST", "/groups", json={"name": "Suporte"})
    gid = created.json()["id"]
    assert created.status_code == 201
    assert env.call("POST", "/groups", json={"name": "Suporte"}).status_code == 422
    assert env.call("PATCH", f"/groups/{gid}", json={"name": "Apoio"}).status_code == 200
    assert env.call("POST", f"/groups/{gid}/members", json={"user_id": USER_3}).status_code == 201
    assert env.call("POST", f"/groups/{gid}/members", json={"user_id": USER_2}).status_code == 404
    groups = {g["name"]: g["members"] for g in env.call("GET", "/groups").json()}
    assert groups["Apoio"] == [USER_3] and groups["Vendas"] == [USER_1]
    assert env.call("DELETE", f"/groups/{gid}/members/{USER_3}").status_code == 200
    assert env.call("DELETE", f"/groups/{gid}/members/{USER_3}").status_code == 404
    assert env.call("DELETE", f"/groups/{gid}").status_code == 200
    assert env.call("DELETE", f"/groups/{gid}").status_code == 404
    other = "22222222-0000-4000-8000-000000000002"  # grupo do tenant B
    assert env.call("PATCH", f"/groups/{other}", json={"name": "x"}).status_code == 404
    assert env.call("DELETE", f"/groups/{other}").status_code == 404
    assert env.call("PATCH", "/groups/nao-uuid", json={"name": "x"}).status_code == 422
    assert GROUP_A in {g["id"] for g in env.call("GET", "/groups").json()}


def test_settings_validation(env: Env) -> None:
    assert env.call("GET", "/settings").json() == {}
    ok = env.call(
        "PATCH", "/settings",
        json={"conversation_retention_days": 90, "forced_offline": True, "block_cloud_for": ["restricted", "confidential"]},
    )  # fmt: skip
    assert ok.status_code == 200 and ok.json()["conversation_retention_days"] == 90
    assert (
        env.call("PATCH", "/settings", json={"general_knowledge": "forbidden"}).status_code == 200
    )
    merged = env.call("GET", "/settings").json()
    assert merged["forced_offline"] is True and merged["general_knowledge"] == "forbidden"
    for bad in (
        {"conversation_retention_days": 45},
        {"general_knowledge": "tudo"},
        {"block_cloud_for": ["secreto"]},
        {"plan": "enterprise"},  # nunca se mexe em plano nem produtos
        {"products": ["local"]},
        {},
    ):
        assert env.call("PATCH", "/settings", json=bad).status_code == 422, bad
    with psycopg.connect(env.rls.admin_dsn) as conn:
        row = conn.execute(
            "select plan, products from app.tenants where id = %s", (TENANT_A,)
        ).fetchone()
    assert row == ("pilot", ["web"])


def test_audit_listing_filters(env: Env) -> None:
    env.call("POST", "/groups", json={"name": "G1"})
    env.call("POST", "/groups", json={"name": "G2"})
    env.call("PATCH", "/settings", json={"forced_offline": False})
    everything = env.call("GET", "/audit").json()
    assert [e["action"] for e in everything["items"]][:3] == [
        "tenant.settings_update", "tenant.group_create", "tenant.group_create",
    ]  # fmt: skip
    only = env.call("GET", "/audit", params={"action": "tenant.group_create"}).json()["items"]
    assert len(only) == 2 and all(e["actor_id"] == USER_1 for e in only)
    assert env.call("GET", "/audit", params={"user": "outro"}).json()["items"] == []
    page = env.call("GET", "/audit", params={"limit": 2}).json()
    assert len(page["items"]) == 2 and page["has_more"] is True and page["next_offset"] == 2
    last = env.call("GET", "/audit", params={"limit": 2, "offset": 2}).json()
    assert len(last["items"]) == 1 and last["has_more"] is False
    assert env.call("GET", "/audit", params={"from": "2999-01-01T00:00:00Z"}).json()["items"] == []
    assert env.call("GET", "/audit", params={"to": "2000-01-01T00:00:00Z"}).json()["items"] == []
    assert env.call("GET", "/audit", params={"action": "Mau Formato"}).status_code == 422
    assert env.call("GET", "/audit", params={"limit": 500}).status_code == 422


def test_inv01_cannot_manage_other_tenant_users(env: Env) -> None:
    assert env.call("PATCH", f"/users/{USER_2}", json={"role": "viewer"}).status_code == 404
    assert USER_2 not in {u["user_id"] for u in env.call("GET", "/users").json()}
    with psycopg.connect(env.rls.admin_dsn) as conn:
        role = conn.execute(
            "select role from app.memberships where user_id = %s and tenant_id = %s",
            (USER_2, TENANT_B),
        ).fetchone()
    assert role == ("member",)
    # a política da BD também impede um não-admin de criar utilizadores
    pool = make_pool(env.rls.dsn_for("app_api"), max_size=1)
    pool.open(wait=True)
    try:
        with (
            Database(pool).tenant_tx(TENANT_B, USER_2) as cur,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            cur.execute("insert into app.users (id, email) values (gen_random_uuid(), 'x@x.test')")
    finally:
        pool.close()


def test_supabase_auth_admin_invite() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "11111111-2222-4333-8444-555555555555"})

    admin = SupabaseAuthAdmin(
        "https://p.supabase.co/", SecretStr("chave-servico"), httpx.MockTransport(handler)
    )
    assert admin.invite("a@x.test", "https://app.test/ok") == "11111111-2222-4333-8444-555555555555"
    assert (
        seen[0].url.path == "/auth/v1/invite"
        and seen[0].url.params["redirect_to"] == "https://app.test/ok"
    )
    assert seen[0].headers["authorization"] == "Bearer chave-servico"
    for response in (httpx.Response(422, json={}), httpx.Response(200, json={"x": 1})):
        broken = SupabaseAuthAdmin(
            "https://p.test", SecretStr("k"), httpx.MockTransport(lambda r, resp=response: resp)
        )  # type: ignore[misc]
        with pytest.raises(UpstreamError):
            broken.invite("a@x.test", None)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("x", request=request)

    with pytest.raises(UpstreamError, match="auth_admin_unreachable"):
        SupabaseAuthAdmin("https://p.test", SecretStr("k"), httpx.MockTransport(down)).invite(
            "a@x.test", None
        )
