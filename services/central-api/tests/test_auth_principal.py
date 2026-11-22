"""Testes de F7-T05 (integração): do token ao Principal (INV-14, INV-15, INV-19)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import psycopg
import pytest
from conftest import TENANT_A, TENANT_B, USER_1, USER_2, USER_3, USER_4, Rls
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from rag_central.auth import (
    CentralAuth,
    PrincipalResolver,
    build_identity_verifier,
    get_principal,
    require_action,
    require_product,
)
from rag_central.db import Database, make_pool
from rag_core.clock import FakeClock
from rag_core.config import Settings
from rag_core.policy import Action
from rag_core.testing.jwt import JwtFactory
from rag_core.types import Principal, Product
from rag_core.web import install_standard_web

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
ISSUER = "https://supabase.test/auth/v1"
JWKS = "https://supabase.test/jwks.json"
CANARY = "CANARIO-token-secreto"


@dataclass
class Env:
    client: TestClient
    factory: JwtFactory
    clock: FakeClock
    rls: Rls

    def token(self, sub: str, **claims: Any) -> dict[str, str]:
        payload = self.factory.claims(sub=sub, email=f"{sub[-1]}@x.test", **claims)
        return {"Authorization": f"Bearer {self.factory.issue(payload)}"}

    def get(self, path: str, sub: str, tenant: str | None = None, **claims: Any) -> httpx.Response:
        headers = self.token(sub, **claims)
        if tenant:
            headers["X-Tenant-Id"] = tenant
        response: httpx.Response = self.client.get(path, headers=headers)
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
    settings = Settings.for_tests(supabase_jwt_issuer=ISSUER, supabase_jwks_url=JWKS)
    pool = make_pool(rls.dsn_for("app_api"), max_size=4)
    pool.open(wait=True)
    clock = FakeClock(datetime(2026, 5, 10, 12, 0, tzinfo=UTC))
    app = FastAPI()
    install_standard_web(app)
    app.state.central_auth = CentralAuth(
        build_identity_verifier(settings, http), PrincipalResolver(Database(pool), clock)
    )

    @app.get("/me")
    def me(principal: Principal = Depends(get_principal)) -> dict[str, Any]:  # noqa: B008
        return {
            "tenant_id": principal.tenant_id, "role": principal.role, "aal": principal.aal,
            "groups": sorted(principal.groups), "products": sorted(principal.products),
        }  # fmt: skip

    @app.get("/local")
    def local(_: Principal = Depends(require_product(Product.LOCAL))) -> dict[str, str]:  # noqa: B008
        return {"ok": "sim"}

    @app.get("/admin")
    def admin(
        _: Principal = Depends(require_action(Action.TENANT_MANAGE_USERS)),  # noqa: B008
    ) -> dict[str, str]:
        return {"ok": "sim"}

    yield Env(TestClient(app, raise_server_exceptions=False), factory, clock, rls)
    pool.close()


def test_no_token_401(env: Env) -> None:
    response = env.client.get("/me")
    assert response.status_code == 401 and response.json()["code"] == "unauthenticated"


def test_invalid_token_401(env: Env) -> None:
    for token in (
        env.factory.expired(),
        env.factory.alg_none(),
        env.factory.wrong_audience(),
        CANARY,
    ):
        response = env.client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert CANARY not in response.text


def test_user_without_membership_403(env: Env) -> None:
    response = env.get("/me", USER_4)
    assert (response.status_code, response.json()["subcode"]) == (403, "no_membership")


def test_single_membership_resolves_role_and_groups(env: Env) -> None:
    response = env.get("/me", USER_1)
    assert response.status_code == 200
    body = response.json()
    assert (body["tenant_id"], body["role"], body["aal"]) == (TENANT_A, "admin", "aal1")
    assert body["groups"] == ["11111111-0000-4000-8000-000000000001"]
    assert body["products"] == ["web"]  # a membership vazia herda os produtos do tenant


def test_new_user_row_is_created_on_first_sight(env: Env, rls: Rls) -> None:
    new_user = "00000000-0000-4000-8000-0000000000aa"
    env.admin(f"insert into app.users (id, email) values ('{new_user}', 'a@x.test')")
    env.admin(
        f"insert into app.memberships (tenant_id, user_id, role) values ('{TENANT_A}', '{new_user}', 'viewer')"
    )
    assert env.get("/me", new_user).status_code == 200
    with psycopg.connect(rls.admin_dsn) as conn:
        row = conn.execute("select count(*) from app.users where id = %s", (new_user,)).fetchone()
    assert row == (1,)


def test_inv14_tenant_header_cannot_escalate(env: Env) -> None:
    # a U1 só é membro de A: pedir o tenant B é 403, e o role nunca vem do cliente
    response = env.get("/me", USER_1, tenant=TENANT_B)
    assert (response.status_code, response.json()["subcode"]) == (403, "not_a_member")
    assert env.get("/me", USER_1, tenant=TENANT_A).json()["role"] == "admin"
    assert env.get("/me", USER_1, tenant="nao-e-uuid").status_code == 403
    assert env.get("/me", USER_1, role="owner", tenant_id=TENANT_B).json()["tenant_id"] == TENANT_A


def test_multiple_memberships_require_header(env: Env) -> None:
    response = env.get("/me", USER_3)
    assert (response.status_code, response.json()["subcode"]) == (400, "tenant_required")
    assert env.get("/me", USER_3, tenant=TENANT_A).json()["role"] == "member"
    assert env.get("/me", USER_3, tenant=TENANT_B).json()["role"] == "editor"
    assert env.get("/me", USER_3, tenant=TENANT_B.upper()).status_code == 200


def test_membership_revocation_effective_after_ttl(env: Env) -> None:
    assert env.get("/me", USER_2).status_code == 200
    env.admin(f"update app.memberships set status = 'disabled' where user_id = '{USER_2}'")
    assert env.get("/me", USER_2).status_code == 200  # ainda em cache
    env.clock.advance(61)
    response = env.get("/me", USER_2)
    assert (response.status_code, response.json()["subcode"]) == (403, "membership_disabled")
    env.admin(f"update app.memberships set status = 'active' where user_id = '{USER_2}'")
    # não há cache de erros: a pertença reativada volta a ser lida de imediato
    assert env.get("/me", USER_2).status_code == 200


def test_suspended_tenant_403(env: Env) -> None:
    env.admin(f"update app.tenants set status = 'suspended' where id = '{TENANT_A}'")
    response = env.get("/me", USER_1)
    assert (response.status_code, response.json()["subcode"]) == (403, "tenant_suspended")
    assert env.get("/me", USER_2).status_code == 200  # os outros tenants não são afetados


def test_inv19_products_intersection(env: Env) -> None:
    assert env.get("/local", USER_1).status_code == 403  # o tenant A só tem "web"
    assert env.get("/local", USER_2).status_code == 200  # o tenant B tem web e local
    env.admin(f"update app.memberships set products = '{{web}}' where user_id = '{USER_2}'")
    env.clock.advance(61)
    response = env.get("/local", USER_2)  # a membership só dá "web": interseção sem "local"
    assert (response.status_code, response.json()["subcode"]) == (403, "product_not_entitled")
    assert env.get("/me", USER_2).json()["products"] == ["web"]
    env.admin(f"update app.memberships set products = '{{local}}' where user_id = '{USER_1}'")
    env.clock.advance(61)
    assert env.get("/me", USER_1).json()["products"] == []  # local não existe no tenant A


def test_inv15_admin_action_requires_aal2(env: Env) -> None:
    assert env.get("/admin", USER_1).status_code == 403  # admin, mas só aal1
    assert env.get("/admin", USER_1, aal="aal2").status_code == 200
    assert env.get("/admin", USER_1, aal="aal3").status_code == 403  # valor desconhecido = aal1
    assert (
        env.get("/admin", USER_2, aal="aal2").status_code == 403
    )  # member nunca gere utilizadores
