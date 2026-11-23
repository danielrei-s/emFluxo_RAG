"""Dispositivos do Produto B: registo, licença, revogação (F8-T07; INV-14, INV-19)."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from rag_core.errors import AccessDenied, NotFound, UpstreamError, ValidationFailed
from rag_core.interfaces import TenantPolicy
from rag_core.policy import Action, can
from rag_core.types import Principal, Product

from rag_central.audit import AuditLogger
from rag_central.auth import get_principal, require_action, require_product
from rag_central.db import Database

router = APIRouter(tags=["devices"])
_UUID = re.compile(r"[0-9a-fA-F-]{36}")
POLICY_FIELDS = ("forced_offline", "block_cloud_for", "wipe_on_revoke")


def _db(request: Request) -> Database:
    db: Database | None = request.app.state.deps.db
    if db is None:
        raise UpstreamError("database_not_configured")
    return db


def _audit(request: Request) -> AuditLogger:
    return AuditLogger(request.app.state.deps.clock)


def _device_id(value: str | None) -> str:
    if not value or not _UUID.fullmatch(value):
        raise ValidationFailed(subcode="invalid_device_id")
    return value.lower()


def require_active_device(
    request: Request,
    principal: Principal = Depends(get_principal),  # noqa: B008
) -> Principal:
    """Dependência comum: um ``X-Device-Id`` revogado (ou alheio) nunca passa (403)."""
    header = request.headers.get("x-device-id")
    if header is None:
        return principal
    device = _device_id(header)
    with _db(request).tenant_tx(principal.tenant_id, principal.user_id) as cur:
        cur.execute(
            "select status from app.devices where id = %s and tenant_id = %s and user_id = %s",
            (device, principal.tenant_id, principal.user_id),
        )
        row = cur.fetchone()
    if row is None:
        raise AccessDenied("unknown_device")
    if row["status"] != "active":
        raise AccessDenied("device_revoked")
    return principal


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    os: str | None = Field(default=None, max_length=40)
    app_version: str | None = Field(default=None, max_length=40)
    public_key: str | None = Field(default=None, max_length=2048)


@router.post("/devices/register", status_code=201)
def register_device(
    body: RegisterRequest,
    request: Request,
    principal: Principal = Depends(require_product(Product.LOCAL)),  # noqa: B008
) -> dict[str, str]:
    with _db(request).tenant_tx(principal.tenant_id, principal.user_id) as cur:
        cur.execute(
            "insert into app.devices (tenant_id, user_id, name, os, app_version, public_key) "
            "values (%s, %s, %s, %s, %s, %s) returning id::text as id",
            (principal.tenant_id, principal.user_id, body.name, body.os, body.app_version,
             body.public_key),
        )  # fmt: skip
        row = cur.fetchone()
        assert row is not None  # noqa: S101 - insert ... returning devolve sempre uma linha
        _audit(request).record(
            cur, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user_id,
            action="device.register", resource_type="device", resource_id=row["id"],
        )  # fmt: skip
    return {"id": row["id"]}


@router.get("/devices/me", response_model=None)
def device_me(
    request: Request,
    principal: Principal = Depends(require_product(Product.LOCAL)),  # noqa: B008
) -> dict[str, Any]:
    """Heartbeat: devolve o estado, a política e (se ativo) a licença de 7 dias."""
    device = _device_id(request.headers.get("x-device-id"))
    with _db(request).tenant_tx(principal.tenant_id, principal.user_id) as cur:
        cur.execute(
            "select status from app.devices where id = %s and tenant_id = %s and user_id = %s",
            (device, principal.tenant_id, principal.user_id),
        )
        row = cur.fetchone()
        if row is None:
            raise NotFound()
        if row["status"] == "active":
            cur.execute("update app.devices set last_seen_at = now() where id = %s", (device,))
        cur.execute("select settings from app.tenants where id = %s", (principal.tenant_id,))
        tenant = cur.fetchone()
    settings = (tenant["settings"] if tenant else {}).get("policy") or {}
    defaults = TenantPolicy(tenant_id=principal.tenant_id)
    policy: dict[str, Any] = {
        "forced_offline": settings.get("forced_offline", defaults.forced_offline),
        "block_cloud_for": settings.get("block_cloud_for", sorted(defaults.block_cloud_for)),
        "allowed_folders": settings.get("allowed_folders", []),
        "wipe_on_revoke": settings.get("wipe_on_revoke", defaults.wipe_on_revoke),
    }
    result: dict[str, Any] = {"status": row["status"], "policy": policy, "entitlement_token": None}
    if row["status"] == "active":
        signer = request.app.state.deps.signer
        if signer is None:
            raise UpstreamError("signing_not_configured")
        result["entitlement_token"] = signer.mint_entitlement_token(
            principal.user_id, principal.tenant_id, device, [str(p) for p in principal.products]
        )
    return result


@router.get("/devices")
def list_devices(
    request: Request,
    principal: Principal = Depends(require_action(Action.DEVICE_REVOKE_ANY)),  # noqa: B008
) -> list[dict[str, Any]]:
    with _db(request).tenant_tx(principal.tenant_id, principal.user_id) as cur:
        cur.execute(
            "select id::text as id, user_id::text as user_id, name, os, app_version, status, "
            "last_seen_at, revoked_at from app.devices where tenant_id = %s order by created_at",
            (principal.tenant_id,),
        )
        rows = cur.fetchall()
    for row in rows:
        row["last_seen_at"], row["revoked_at"] = _iso(row["last_seen_at"]), _iso(row["revoked_at"])
    return rows


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


@router.post("/devices/{device_id}/revoke")
def revoke_device(
    device_id: str,
    request: Request,
    principal: Principal = Depends(get_principal),  # noqa: B008
) -> dict[str, str]:
    device = _device_id(device_id)
    any_device = can(principal, Action.DEVICE_REVOKE_ANY)
    if not (any_device or can(principal, Action.DEVICE_REVOKE_OWN)):
        raise AccessDenied("insufficient_role_or_aal")
    with _db(request).tenant_tx(principal.tenant_id, principal.user_id) as cur:
        cur.execute(
            "update app.devices set status = 'revoked', revoked_at = now(), revoked_by = %s "
            "where id = %s and tenant_id = %s and (%s or user_id = %s) returning id",
            (principal.user_id, device, principal.tenant_id, any_device, principal.user_id),
        )
        if cur.fetchone() is None:
            raise NotFound()  # inexistente ou de outro utilizador (sem ser admin)
        _audit(request).record(
            cur, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user_id,
            action="device.revoke", resource_type="device", resource_id=device,
        )  # fmt: skip
    return {"status": "revoked"}
