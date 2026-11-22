"""Claims dos tokens aceites pelo gateway (F6-T02)."""

from __future__ import annotations

from typing import Any

from rag_core.errors import Unauthenticated
from rag_core.types import Frozen

SERVICE_TOKEN_MAX_TTL_S = 60
SERVICE_PURPOSE_CHAT = "chat"
REQUIRED_CLAIMS = ("exp", "iat", "sub", "iss", "aud")


class ServiceClaims(Frozen):
    """Token de serviço (Central API → gateway): curto, para um tenant e utilizador."""

    sub: str
    iss: str
    tenant_id: str
    user_id: str
    purpose: str
    exp: int
    iat: int


def parse_service_claims(claims: dict[str, Any]) -> ServiceClaims:
    """Valida o tipo, o âmbito e a validade (≤ 60 s) de um token de serviço já verificado."""
    if claims.get("typ") != "service":
        raise Unauthenticated("not_service_token")
    tenant_id, user_id = claims.get("tenant_id"), claims.get("user_id")
    if (
        not isinstance(tenant_id, str)
        or not tenant_id
        or not isinstance(user_id, str)
        or not user_id
    ):
        raise Unauthenticated("missing_tenant_or_user")
    if claims.get("purpose") != SERVICE_PURPOSE_CHAT:
        raise Unauthenticated("wrong_purpose")
    try:
        exp, iat = int(claims["exp"]), int(claims["iat"])
    except (KeyError, TypeError, ValueError) as exc:
        raise Unauthenticated("missing_claim") from exc
    if exp - iat > SERVICE_TOKEN_MAX_TTL_S:
        raise Unauthenticated("ttl_too_long")
    return ServiceClaims(
        sub=str(claims["sub"]),
        iss=str(claims["iss"]),
        tenant_id=tenant_id,
        user_id=user_id,
        purpose=SERVICE_PURPOSE_CHAT,
        exp=exp,
        iat=iat,
    )
