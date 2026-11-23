"""Testes de F9-T02 (integração): funcionalidades por tenant com cache de 60 s (INV-19)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg
import pytest
from conftest import TENANT_A, USER_1, Rls
from fastapi.testclient import TestClient
from rag_central.app import CentralDeps, create_app
from rag_central.auth import CentralAuth, PrincipalResolver, build_identity_verifier
from rag_central.db import Database, make_pool
from rag_central.features import FeatureService
from rag_core.clock import FakeClock
from rag_core.config import Settings
from rag_core.errors import ValidationFailed
from rag_core.modules import ModuleRegistry
from rag_core.testing.jwt import JwtFactory

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
ISSUER = "https://supabase.test/auth/v1"
MODULES = Path(__file__).resolve().parents[3] / "modules"


@dataclass
class Env:
    client: TestClient
    factory: JwtFactory
    clock: FakeClock
    registry: ModuleRegistry
    rls: Rls

    def ping(self) -> httpx.Response:
        token = self.factory.issue(self.factory.claims(sub=USER_1))
        response: httpx.Response = self.client.get(
            "/v1/modules/example/ping", headers={"Authorization": f"Bearer {token}"}
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
    clock = FakeClock(datetime(2026, 5, 10, tzinfo=UTC))
    registry = ModuleRegistry.load(MODULES)
    auth = CentralAuth(build_identity_verifier(settings, http), PrincipalResolver(db, clock))
    deps = CentralDeps(auth=auth, db=db, features=FeatureService(db, registry, clock), clock=clock)
    yield Env(TestClient(app=create_app(settings, deps), raise_server_exceptions=False),
              factory, clock, registry, rls)  # fmt: skip
    pool.close()


def test_inv19_disabled_feature_404_enabled_200(env: Env) -> None:
    assert env.ping().status_code == 404  # sem linha: vale o default do manifesto (desligado)
    env.admin(
        "insert into app.tenant_features (tenant_id, feature, enabled) "
        f"values ('{TENANT_A}', 'example', true)"
    )
    assert env.ping().status_code == 404  # ainda em cache (60 s)
    env.clock.advance(61)
    response = env.ping()
    assert response.status_code == 200 and response.json() == {"pong": "ok"}
    env.admin(f"update app.tenant_features set enabled = false where tenant_id = '{TENANT_A}'")
    env.clock.advance(61)
    assert env.ping().status_code == 404


def test_default_enabled_applies_when_there_is_no_row(env: Env) -> None:
    service = FeatureService(
        env.client.app.state.deps.db,
        env.registry,
        env.clock,  # type: ignore[attr-defined]
    )
    assert service.state(TENANT_A, USER_1, "example") == (False, {})
    env.admin(
        "insert into app.tenant_features (tenant_id, feature, enabled, config) "
        f"values ('{TENANT_A}', 'example', true, '{{\"max_items\": 3}}')"
    )
    env.clock.advance(61)
    assert service.state(TENANT_A, USER_1, "example") == (True, {"max_items": 3})


def test_invalid_feature_config_422(env: Env) -> None:
    for config in ({"max_items": "muitos"}, {"outro": 1}, {"greeting": "x" * 41}):
        with pytest.raises(ValidationFailed) as exc:
            env.registry.validate_config("example", config)
        assert exc.value.subcode == "invalid_feature_config"


def test_unauthenticated_and_unconfigured(env: Env) -> None:
    assert env.client.get("/v1/modules/example/ping").status_code == 401
    bare = TestClient(
        create_app(Settings.for_tests(), CentralDeps()), raise_server_exceptions=False
    )
    assert bare.get("/v1/modules/example/ping").status_code == 401
