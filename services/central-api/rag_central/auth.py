"""Do token ao ``Principal``, sempre no servidor (F7-T05; INV-14, INV-15, INV-19).

O ``tenant`` nunca vem do token do cliente: o cabeçalho ``X-Tenant-Id`` só escolhe entre
pertenças que o utilizador já tem na BD; ``aal`` vem do token já verificado.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Depends, Request
from rag_core.auth import CompositeVerifier, JwksVerifier
from rag_core.config import Settings
from rag_core.errors import AccessDenied, BadRequest, Unauthenticated
from rag_core.interfaces import Clock
from rag_core.policy import Action, can
from rag_core.types import Principal, Product, Role

from rag_central.db import Database

DEFAULT_USER_AUDIENCE = "authenticated"
CACHE_TTL_S = 60


def build_identity_verifier(
    settings: Settings, http: httpx.Client | None = None
) -> CompositeVerifier:
    """Verificador dos tokens do Supabase (JWKS assimétrico, ``aud = authenticated``)."""
    verifiers: dict[str, JwksVerifier] = {}
    if settings.supabase_jwt_issuer and settings.supabase_jwks_url:
        verifiers[settings.supabase_jwt_issuer] = JwksVerifier(
            settings.supabase_jwks_url,
            settings.supabase_jwt_issuer,
            settings.supabase_jwt_audience or DEFAULT_USER_AUDIENCE,
            http=http,
            env=settings.env,
        )
    return CompositeVerifier(verifiers)


@dataclass(frozen=True)
class _Resolved:
    principal: Principal
    expires: float


class PrincipalResolver:
    """Resolve ``sub`` (+ ``X-Tenant-Id``) numa pertença ativa; a resposta fica 60 s em cache."""

    def __init__(self, db: Database, clock: Clock, cache_ttl_s: int = CACHE_TTL_S) -> None:
        self._db = db
        self._clock = clock
        self._ttl = cache_ttl_s
        self._cache: dict[tuple[str, str | None], _Resolved] = {}

    def resolve(self, claims: dict[str, Any], tenant_header: str | None = None) -> Principal:
        user_id = str(claims.get("sub") or "")
        if not user_id:
            raise Unauthenticated("missing_sub")
        aal = "aal2" if claims.get("aal") == "aal2" else "aal1"
        now = self._clock.now().timestamp()
        cached = self._cache.get((user_id, tenant_header))
        if cached is not None and cached.expires > now:
            return cached.principal.model_copy(update={"aal": aal})
        principal = self._load(user_id, str(claims.get("email") or ""), tenant_header)
        self._cache[(user_id, tenant_header)] = _Resolved(principal, now + self._ttl)
        return principal.model_copy(update={"aal": aal})

    def _load(self, user_id: str, email: str, tenant_header: str | None) -> Principal:
        with self._db.user_tx(user_id) as cur:
            if email:  # primeira vez que o utilizador aparece
                cur.execute(
                    "insert into app.users (id, email) values (%s, %s) on conflict (id) do nothing",
                    (user_id, email),
                )
            cur.execute(
                "select tenant_id::text as tenant_id, role, products, status "
                "from app.memberships where user_id = %s",
                (user_id,),
            )
            memberships = cur.fetchall()
        membership = self._choose(memberships, tenant_header)
        tenant_id = membership["tenant_id"]
        with self._db.tenant_tx(tenant_id, user_id) as cur:
            cur.execute("select status, products from app.tenants where id = %s", (tenant_id,))
            tenant = cur.fetchone()
            cur.execute(
                "select group_id::text as group_id from app.group_members "
                "where tenant_id = %s and user_id = %s",
                (tenant_id, user_id),
            )
            groups = frozenset(row["group_id"] for row in cur.fetchall())
        if tenant is None or tenant["status"] != "active":
            raise AccessDenied("tenant_suspended")
        tenant_products = {Product(p) for p in tenant["products"]}
        own = {Product(p) for p in membership["products"]}
        products = frozenset(own & tenant_products if own else tenant_products)
        return Principal(
            tenant_id=tenant_id,
            user_id=user_id,
            role=Role(membership["role"]),
            groups=groups,
            products=products,
        )

    @staticmethod
    def _choose(memberships: list[dict[str, Any]], header: str | None) -> dict[str, Any]:
        if header is not None:
            chosen = next((m for m in memberships if m["tenant_id"] == header.lower()), None)
            if chosen is None:
                raise AccessDenied("not_a_member")  # INV-14: o cabeçalho não escala privilégios
        else:
            active = [m for m in memberships if m["status"] == "active"]
            if len(active) > 1:
                raise BadRequest("tenant_required")
            if not memberships:
                raise AccessDenied("no_membership")
            chosen = active[0] if active else memberships[0]
        if chosen["status"] != "active":
            raise AccessDenied("membership_disabled")
        return chosen


class CentralAuth:
    """Verificador + resolver; fica em ``app.state.central_auth``."""

    def __init__(self, verifier: CompositeVerifier, resolver: PrincipalResolver) -> None:
        self.verifier = verifier
        self.resolver = resolver


def _bearer(authorization: str | None) -> str:
    if not authorization:
        raise Unauthenticated("missing_token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthenticated("malformed_authorization")
    return token.strip()


def get_principal(request: Request) -> Principal:
    """Dependência FastAPI: 401 sem token válido, 403 sem pertença, 400 se faltar o tenant."""
    auth: CentralAuth | None = getattr(request.app.state, "central_auth", None)
    if auth is None:
        raise Unauthenticated("auth_not_configured")
    claims = auth.verifier.verify(_bearer(request.headers.get("authorization")))
    return auth.resolver.resolve(claims, request.headers.get("x-tenant-id"))


def require_product(product: Product) -> Callable[[Principal], Principal]:
    def dependency(principal: Principal = Depends(get_principal)) -> Principal:  # noqa: B008
        if product not in principal.products:
            raise AccessDenied("product_not_entitled")  # INV-19
        return principal

    return dependency


def require_action(action: Action) -> Callable[[Principal], Principal]:
    def dependency(principal: Principal = Depends(get_principal)) -> Principal:  # noqa: B008
        if not can(principal, action):
            raise AccessDenied("insufficient_role_or_aal")  # INV-15 para ações de administração
        return principal

    return dependency
