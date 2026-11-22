"""Testes de F6-T02: autenticação do gateway (serviço e utilizador + dispositivo; INV-14)."""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from rag_core.auth import CompositeVerifier, JwksVerifier
from rag_core.config import Settings
from rag_core.testing.jwt import AUDIENCE, ISSUER, JwtFactory
from rag_core.types import Principal, Role
from rag_gateway.app import GatewayDeps, create_app
from rag_gateway.auth import AuthContext, Authenticator, build_authenticator, require_auth
from rag_gateway.ports import FakeDeviceStatusProvider, FakePrincipalResolver

# O TestClient usa um par de sockets internos (loopback); nada sai da máquina.
pytestmark = pytest.mark.enable_socket

SUPABASE_ISSUER = "https://supabase.test/auth/v1"
CENTRAL_JWKS = "https://central.test/jwks.json"
SUPABASE_JWKS = "https://supabase.test/jwks.json"
CANARY = "CANARIO-token-no-erro"


@pytest.fixture
def central() -> JwtFactory:
    return JwtFactory()


@pytest.fixture
def supabase() -> JwtFactory:
    return JwtFactory(issuer=SUPABASE_ISSUER, audience="authenticated")


@pytest.fixture
def devices() -> FakeDeviceStatusProvider:
    return FakeDeviceStatusProvider()


def _http(central: JwtFactory, supabase: JwtFactory) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        factory = {CENTRAL_JWKS: central, SUPABASE_JWKS: supabase}[str(request.url)]
        return httpx.Response(200, json=factory.jwks())

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def client(
    central: JwtFactory, supabase: JwtFactory, devices: FakeDeviceStatusProvider
) -> TestClient:
    http = _http(central, supabase)
    verifier = CompositeVerifier(
        {
            ISSUER: JwksVerifier(CENTRAL_JWKS, ISSUER, AUDIENCE, http=http),
            SUPABASE_ISSUER: JwksVerifier(
                SUPABASE_JWKS, SUPABASE_ISSUER, "authenticated", http=http
            ),
        }
    )
    resolver = FakePrincipalResolver(
        {
            "user-1": Principal(
                tenant_id="t1", user_id="u1", role=Role.EDITOR, groups=frozenset({"g"})
            )
        }
    )
    authenticator = Authenticator(
        verifier, central_issuer=ISSUER, resolver=resolver, device_status=devices
    )
    app = create_app(Settings.for_tests(), GatewayDeps(authenticator=authenticator))

    @app.get("/whoami")
    def whoami(ctx: AuthContext = Depends(require_auth)) -> dict[str, Any]:  # noqa: B008
        return {
            "kind": ctx.kind,
            "tenant_id": ctx.principal.tenant_id,
            "user_id": ctx.principal.user_id,
            "role": ctx.principal.role,
            "device_id": ctx.device_id,
            "purpose": ctx.purpose,
        }

    return TestClient(app, raise_server_exceptions=False)


def _get(client: TestClient, token: str | None, **headers: str) -> httpx.Response:
    sent = {"Authorization": f"Bearer {token}"} if token else {}
    response: httpx.Response = client.get("/whoami", headers={**sent, **headers})
    return response


def _service(central: JwtFactory, **overrides: Any) -> str:
    return central.issue(central.service_claims(**overrides))


def _user_token(supabase: JwtFactory, sub: str = "user-1") -> str:
    return supabase.issue(supabase.claims(sub=sub))


def test_service_token_authenticates_the_acting_user(
    client: TestClient, central: JwtFactory
) -> None:
    response = _get(client, central.issue())
    assert response.status_code == 200
    assert response.json() == {
        "kind": "service", "tenant_id": "t1", "user_id": "u1", "role": "member",
        "device_id": None, "purpose": "chat",
    }  # fmt: skip


def test_missing_or_malformed_credentials_are_401_problem_json(client: TestClient) -> None:
    for headers in (
        {},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer  "},
    ):
        response = client.get("/whoami", headers=headers)
        assert response.status_code == 401, headers
        assert response.json()["code"] == "unauthenticated"
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.headers["www-authenticate"] == "Bearer"


def test_invalid_tokens_are_401_without_echoing_the_token(
    client: TestClient, central: JwtFactory
) -> None:
    now = int(time.time())
    for token in (
        central.expired(),
        central.wrong_audience(),
        central.alg_none(),
        central.hs256_with_public_key(),
        central.unknown_kid(),
        f"{CANARY}.{CANARY}.{CANARY}",
        _service(central, iat=now, exp=now + 120),  # TTL de serviço acima de 60 s
        _service(central, tenant_id=""),  # sem tenant
        _service(central, purpose="outro"),
    ):
        response = _get(client, token)
        assert response.status_code == 401, token[:20]
        assert CANARY not in response.text
        assert set(response.json()) <= {"type", "title", "status", "code", "subcode", "request_id"}


def test_unknown_issuer_is_401(client: TestClient) -> None:
    stranger = JwtFactory(issuer="https://desconhecido.test")
    assert _get(client, stranger.issue()).status_code == 401


def test_user_token_needs_a_device_and_resolves_the_principal(
    client: TestClient, supabase: JwtFactory
) -> None:
    token = _user_token(supabase)
    assert _get(client, token).status_code == 401  # sem X-Device-Id
    ok = _get(client, token, **{"X-Device-Id": "dev-1"})
    assert ok.status_code == 200
    assert ok.json() == {
        "kind": "device", "tenant_id": "t1", "user_id": "u1", "role": "editor",
        "device_id": "dev-1", "purpose": "chat",
    }  # fmt: skip
    unknown = _get(client, _user_token(supabase, "ninguem"), **{"X-Device-Id": "dev-1"})
    assert (unknown.status_code, unknown.json()["code"]) == (403, "access_denied")


def test_inv14_revoked_device_forbidden(
    client: TestClient, supabase: JwtFactory, devices: FakeDeviceStatusProvider
) -> None:
    token = _user_token(supabase)
    assert _get(client, token, **{"X-Device-Id": "dev-1"}).status_code == 200
    devices.revoke("t1", "u1", "dev-1")
    revoked = _get(client, token, **{"X-Device-Id": "dev-1"})
    assert (revoked.status_code, revoked.json()["code"]) == (403, "access_denied")
    assert _get(client, token, **{"X-Device-Id": "dev-2"}).status_code == 200  # outro dispositivo


def test_a_user_token_cannot_pass_as_a_service_token(
    client: TestClient, supabase: JwtFactory
) -> None:
    claims = supabase.claims(typ="service", tenant_id="t-outro", user_id="u-outro", purpose="chat")
    response = _get(client, supabase.issue(claims))
    assert response.status_code == 401  # sem dispositivo: nunca é tratado como serviço


def test_routes_without_a_configured_authenticator_are_401() -> None:
    app = create_app(Settings.for_tests())

    @app.get("/protegido")
    def protected(ctx: AuthContext = Depends(require_auth)) -> dict[str, str]:  # noqa: B008
        return {"ok": ctx.kind}

    response = TestClient(app, raise_server_exceptions=False).get("/protegido")
    assert response.status_code == 401


def test_build_authenticator_from_settings(central: JwtFactory, supabase: JwtFactory) -> None:
    settings = Settings.for_tests(
        central_issuer=ISSUER,
        central_jwks_url=CENTRAL_JWKS,
        supabase_jwt_issuer=SUPABASE_ISSUER,
        supabase_jwks_url=SUPABASE_JWKS,
    )
    principal = Principal(tenant_id="t1", user_id="u1", role=Role.MEMBER)
    authenticator = build_authenticator(
        settings,
        FakePrincipalResolver({"user-1": principal}),
        FakeDeviceStatusProvider(),
        http=_http(central, supabase),
    )
    assert authenticator.authenticate(f"Bearer {central.issue()}", None).kind == "service"
    device = authenticator.authenticate(f"Bearer {_user_token(supabase)}", "d1")
    assert device.kind == "device" and device.device_id == "d1"
    only_central = build_authenticator(
        Settings.for_tests(central_issuer=ISSUER, central_jwks_url=CENTRAL_JWKS),
        FakePrincipalResolver(),
        FakeDeviceStatusProvider(),
        http=_http(central, supabase),
    )
    assert only_central.authenticate(f"Bearer {central.issue()}", None).kind == "service"
