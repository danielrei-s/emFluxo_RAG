"""Endpoints internos para o gateway (``/internal/v1``; F8-T06).

Nunca chegam pela edge: pedidos com cabeçalhos da Cloudflare dão 404, e todos exigem a chave
interna (comparada em tempo constante).
"""

from __future__ import annotations

import hmac
import re
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from rag_core.errors import AccessDenied, NotFound, Unauthenticated, ValidationFailed
from rag_core.interfaces import TenantPolicy

from rag_central.db import Database

router = APIRouter(tags=["internal"])
EDGE_HEADERS = ("cf-connecting-ip", "cf-ray")
_UUID = r"[0-9a-fA-F-]{36}"
POLICY_FIELDS = set(TenantPolicy.model_fields) - {"tenant_id", "status", "products"}
MAX_BATCH = 500


def require_internal(request: Request) -> None:
    if any(header in request.headers for header in EDGE_HEADERS):
        raise NotFound()  # estes endpoints nunca vêm da edge
    key = request.app.state.settings.internal_api_key
    if key is None:
        raise Unauthenticated("internal_api_not_configured")
    sent = request.headers.get("x-internal-key", "")
    if not hmac.compare_digest(sent.encode(), key.get_secret_value().encode()):
        raise Unauthenticated("bad_internal_key")


def _db(request: Request) -> Database:
    db: Database | None = request.app.state.deps.db
    if db is None:
        raise Unauthenticated("database_not_configured")
    return db


def _uuid(value: str) -> str:
    if not re.fullmatch(_UUID, value):
        raise ValidationFailed(subcode="invalid_id")
    return value.lower()


@router.get("/tenants/{tenant_id}/policy", response_model=None)
def tenant_policy(
    tenant_id: str, request: Request, _: None = Depends(require_internal)
) -> dict[str, Any]:
    tenant_id = _uuid(tenant_id)
    with _db(request).tenant_tx(tenant_id) as cur:
        cur.execute(
            "select status, products, settings from app.tenants where id = %s", (tenant_id,)
        )
        row = cur.fetchone()
    if row is None:
        raise NotFound()
    overrides = {
        k: v for k, v in (row["settings"].get("policy") or {}).items() if k in POLICY_FIELDS
    }
    try:
        policy = TenantPolicy.model_validate(
            {
                **overrides,
                "tenant_id": tenant_id,
                "status": row["status"],
                "products": row["products"],
            }
        )
    except ValidationError as exc:
        raise ValidationFailed(subcode="invalid_policy") from exc
    return policy.model_dump(mode="json")


class UsageEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    user_id: str | None = None
    device_id: str | None = None
    model: str = Field(max_length=64)
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    ttft_ms: int | None = Field(default=None, ge=0)
    status: Literal["ok", "error", "rejected"]
    error_code: str | None = Field(default=None, pattern=r"^[a-z0-9_]{1,64}$")
    at: datetime


class UsageBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[UsageEventIn] = Field(max_length=MAX_BATCH)


@router.post("/usage", status_code=202)
def record_usage(
    batch: UsageBatch, request: Request, _: None = Depends(require_internal)
) -> dict[str, int]:
    db = _db(request)
    by_tenant: dict[str, list[UsageEventIn]] = {}
    for event in batch.events:
        by_tenant.setdefault(_uuid(event.tenant_id), []).append(event)
    for tenant_id, events in by_tenant.items():
        with db.tenant_tx(tenant_id) as cur:
            cur.executemany(
                "insert into app.usage_events (tenant_id, user_id, device_id, model, tokens_in, "
                "tokens_out, latency_ms, ttft_ms, status, error_code, at) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (tenant_id, e.user_id, e.device_id, e.model, e.tokens_in, e.tokens_out,
                     e.latency_ms, e.ttft_ms, e.status, e.error_code, e.at)
                    for e in events
                ],
            )  # fmt: skip
    return {"accepted": len(batch.events)}


@router.get("/tenants/{tenant_id}/usage/month")
def usage_month(
    tenant_id: str, request: Request, _: None = Depends(require_internal)
) -> dict[str, int]:
    """Tokens (entrada + saída) dos pedidos ``ok`` do mês civil (UTC) corrente."""
    tenant_id = _uuid(tenant_id)
    now = datetime.now(UTC)
    start = datetime(now.year, now.month, 1, tzinfo=UTC)
    with _db(request).tenant_tx(tenant_id) as cur:
        cur.execute(
            "select coalesce(sum(tokens_in + tokens_out), 0)::bigint as tokens "
            "from app.usage_events where tenant_id = %s and status = 'ok' and at >= %s",
            (tenant_id, start),
        )
        row = cur.fetchone()
    return {"tokens": int(row["tokens"]) if row else 0}


@router.get("/devices/{device_id}/status")
def device_status(
    device_id: str,
    request: Request,
    tenant_id: str = Query(),
    user_id: str | None = Query(default=None),
    _: None = Depends(require_internal),
) -> dict[str, str]:
    tenant_id, device_id = _uuid(tenant_id), _uuid(device_id)
    with _db(request).tenant_tx(tenant_id) as cur:
        cur.execute(
            "select status, user_id::text as user_id from app.devices "
            "where id = %s and tenant_id = %s",
            (device_id, tenant_id),
        )
        row = cur.fetchone()
    if row is None or (user_id is not None and row["user_id"] != user_id.lower()):
        raise NotFound()  # o dispositivo de outro utilizador conta como inexistente
    return {"status": str(row["status"])}


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sub: str = Field(max_length=64)
    tenant_id: str | None = None
    device_id: str | None = None


@router.post("/principals/resolve")
def resolve_principal(
    body: ResolveRequest, request: Request, _: None = Depends(require_internal)
) -> dict[str, Any]:
    auth = request.app.state.central_auth
    if auth is None:
        raise Unauthenticated("auth_not_configured")
    tenant = _uuid(body.tenant_id) if body.tenant_id else None
    principal = auth.resolver.resolve({"sub": body.sub}, tenant)
    if body.device_id is not None and "local" not in principal.products:
        raise AccessDenied("product_not_entitled")  # dispositivos só existem no produto local
    return {
        "tenant_id": principal.tenant_id,
        "user_id": principal.user_id,
        "role": principal.role,
        "groups": sorted(principal.groups),
        "products": sorted(principal.products),
    }
