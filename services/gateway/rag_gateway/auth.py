"""Autenticação do gateway (F6-T02): token de serviço ou token de utilizador + dispositivo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

import httpx
from fastapi import Request
from rag_core.auth import CompositeVerifier, JwksVerifier, parse_service_claims
from rag_core.config import Settings
from rag_core.errors import AccessDenied, Unauthenticated
from rag_core.types import Principal, Role

from rag_gateway.ports import DeviceStatusProvider, PrincipalResolver

SERVICE_AUDIENCE = "rag-gateway"
DEFAULT_USER_AUDIENCE = "authenticated"


class TokenVerifier(Protocol):
    def verify(self, token: str) -> dict[str, object]: ...


@dataclass(frozen=True)
class AuthContext:
    """Quem fez o pedido, já verificado."""

    principal: Principal
    kind: Literal["service", "device"]
    purpose: str
    device_id: str | None = None


def _bearer(authorization: str | None) -> str:
    if not authorization:
        raise Unauthenticated("missing_token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthenticated("malformed_authorization")
    return token.strip()


class Authenticator:
    """Aceita (a) tokens de serviço da Central API e (b) tokens de utilizador com dispositivo."""

    def __init__(
        self,
        verifier: TokenVerifier,
        *,
        central_issuer: str | None,
        resolver: PrincipalResolver,
        device_status: DeviceStatusProvider,
    ) -> None:
        self._verifier = verifier
        self._central_issuer = central_issuer
        self._resolver = resolver
        self._devices = device_status

    def authenticate(self, authorization: str | None, device_id: str | None) -> AuthContext:
        claims = self._verifier.verify(_bearer(authorization))
        if self._central_issuer is not None and claims.get("iss") == self._central_issuer:
            service = parse_service_claims(claims)
            acting = Principal(
                tenant_id=service.tenant_id, user_id=service.user_id, role=Role.MEMBER
            )
            return AuthContext(acting, "service", service.purpose)
        if not device_id:
            raise Unauthenticated("missing_device_id")
        principal = self._resolver.resolve(claims, device_id)
        if principal is None:
            raise AccessDenied("unknown_principal")
        if not self._devices.is_active(principal.tenant_id, principal.user_id, device_id):
            raise AccessDenied("device_revoked")  # INV-14: revogação vale já
        known = principal.model_copy(update={"device_id": device_id})
        return AuthContext(known, "device", "chat", device_id)


def build_authenticator(
    settings: Settings,
    resolver: PrincipalResolver,
    device_status: DeviceStatusProvider,
    http: httpx.Client | None = None,
) -> Authenticator:
    """Verificadores a partir da configuração: Central (serviço) e Supabase (utilizadores)."""
    verifiers: dict[str, JwksVerifier] = {}
    if settings.central_issuer and settings.central_jwks_url:
        verifiers[settings.central_issuer] = JwksVerifier(
            settings.central_jwks_url, settings.central_issuer, SERVICE_AUDIENCE, http=http,
            env=settings.env,
        )  # fmt: skip
    if settings.supabase_jwt_issuer and settings.supabase_jwks_url:
        verifiers[settings.supabase_jwt_issuer] = JwksVerifier(
            settings.supabase_jwks_url,
            settings.supabase_jwt_issuer,
            settings.supabase_jwt_audience or DEFAULT_USER_AUDIENCE,
            http=http,
            env=settings.env,
        )
    return Authenticator(
        CompositeVerifier(verifiers),
        central_issuer=settings.central_issuer,
        resolver=resolver,
        device_status=device_status,
    )


def require_auth(request: Request) -> AuthContext:
    """Dependência FastAPI: autentica o pedido ou levanta ``Unauthenticated``/``AccessDenied``."""
    authenticator: Authenticator | None = request.app.state.deps.authenticator
    if authenticator is None:
        raise Unauthenticated("auth_not_configured")
    return authenticator.authenticate(
        request.headers.get("authorization"), request.headers.get("x-device-id")
    )
