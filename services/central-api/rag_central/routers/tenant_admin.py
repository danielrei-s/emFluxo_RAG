"""Administração do tenant (``/v1/tenant``; F8-T10): utilizadores, grupos, definições, auditoria.

Tudo exige as ações de administração da C8 (e portanto ``aal2``, INV-15) e corre dentro do tenant
do administrador (INV-01): não há forma de apontar para outro tenant.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, ConfigDict, Field
from rag_core.errors import AccessDenied, NotFound, UpstreamError, ValidationFailed
from rag_core.policy import Action
from rag_core.types import Classification, Principal

from rag_central.audit import AuditLogger
from rag_central.auth import require_action
from rag_central.db import Database

router = APIRouter(prefix="/tenant", tags=["tenant-admin"])
_UUID = re.compile(r"[0-9a-fA-F-]{36}")
ManageUsers = Annotated[Principal, Depends(require_action(Action.TENANT_MANAGE_USERS))]
ManageSettings = Annotated[Principal, Depends(require_action(Action.TENANT_MANAGE_SETTINGS))]
ReadAudit = Annotated[Principal, Depends(require_action(Action.AUDIT_READ))]
AssignableRole = Literal["admin", "editor", "member", "viewer"]  # nunca "owner"


def _db(request: Request) -> Database:
    db: Database | None = request.app.state.deps.db
    if db is None:
        raise UpstreamError("database_not_configured")
    return db


def _audit(request: Request, cur: Any, principal: Principal, action: str, resource: str) -> None:
    AuditLogger(request.app.state.deps.clock).record(
        cur, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user_id,
        action=action, resource_type="tenant", resource_id=resource,
    )  # fmt: skip


def _id(value: str) -> str:
    if not _UUID.fullmatch(value):
        raise ValidationFailed(subcode="invalid_id")
    return value.lower()


# ----------------------------------------------------------------------------- utilizadores
class InviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: AssignableRole = "member"
    redirect_to: str | None = Field(default=None, max_length=300)
    products: list[Literal["web", "local"]] = Field(default_factory=list)


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AssignableRole | None = None
    status: Literal["active", "disabled"] | None = None


@router.get("/users")
def list_users(request: Request, principal: ManageUsers) -> list[dict[str, Any]]:
    with _db(request).tenant_tx(principal.tenant_id, principal.user_id) as cur:
        cur.execute(
            "select m.user_id::text as user_id, u.email, m.role, m.status, m.products "
            "from app.memberships m join app.users u on u.id = m.user_id "
            "where m.tenant_id = %s order by u.email",
            (principal.tenant_id,),
        )
        return cur.fetchall()


@router.post("/users", status_code=201)
def invite_user(body: InviteRequest, request: Request, principal: ManageUsers) -> dict[str, str]:
    auth_admin = request.app.state.deps.auth_admin
    if auth_admin is None:
        raise UpstreamError("auth_admin_not_configured")
    user_id = auth_admin.invite(body.email, body.redirect_to)
    with _db(request).tenant_tx(principal.tenant_id, principal.user_id) as cur:
        # sem ON CONFLICT: a política de SELECT esconde utilizadores de outros tenants, por isso o
        # conflito (utilizador já existente noutro tenant) resolve-se com um savepoint
        try:
            with cur.connection.transaction():
                cur.execute(
                    "insert into app.users (id, email) values (%s, %s)", (user_id, body.email)
                )
        except UniqueViolation:
            pass
        cur.execute(
            "insert into app.memberships (tenant_id, user_id, role, products, status) "
            "values (%s, %s, %s, %s, 'invited') on conflict (tenant_id, user_id) do nothing "
            "returning user_id",
            (principal.tenant_id, user_id, body.role, body.products),
        )
        created = cur.fetchone() is not None
        if created:
            _audit(request, cur, principal, "tenant.user_invite", user_id)
    if not created:
        raise ValidationFailed(subcode="already_member")
    return {"user_id": user_id}


@router.patch("/users/{user_id}")
def update_user(
    user_id: str, body: UpdateUserRequest, request: Request, principal: ManageUsers
) -> dict[str, str]:
    target = _id(user_id)
    if body.role is None and body.status is None:
        raise ValidationFailed(subcode="nothing_to_update")
    with _db(request).tenant_tx(principal.tenant_id, principal.user_id) as cur:
        cur.execute(
            "select role from app.memberships where tenant_id = %s and user_id = %s",
            (principal.tenant_id, target),
        )
        row = cur.fetchone()
        if row is None:
            raise NotFound()
        if row["role"] == "owner":
            raise AccessDenied("cannot_modify_owner")
        cur.execute(
            "update app.memberships set role = coalesce(%s, role), status = coalesce(%s, status) "
            "where tenant_id = %s and user_id = %s",
            (body.role, body.status, principal.tenant_id, target),
        )
        _audit(request, cur, principal, "tenant.user_update", target)
    return {"status": "updated"}


# ----------------------------------------------------------------------------- grupos
class GroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)


class MemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str


@router.get("/groups")
def list_groups(request: Request, principal: ManageUsers) -> list[dict[str, Any]]:
    with _db(request).tenant_tx(principal.tenant_id, principal.user_id) as cur:
        cur.execute(
            "select g.id::text as id, g.name, "
            "coalesce(array_agg(gm.user_id::text) filter (where gm.user_id is not null), '{}') "
            "as members from app.groups g left join app.group_members gm on gm.group_id = g.id "
            "where g.tenant_id = %s group by g.id order by g.name",
            (principal.tenant_id,),
        )
        return cur.fetchall()


@router.post("/groups", status_code=201)
def create_group(body: GroupRequest, request: Request, principal: ManageUsers) -> dict[str, str]:
    with _db(request).tenant_tx(principal.tenant_id, principal.user_id) as cur:
        cur.execute(
            "insert into app.groups (tenant_id, name) values (%s, %s) "
            "on conflict (tenant_id, name) do nothing returning id::text as id",
            (principal.tenant_id, body.name),
        )
        row = cur.fetchone()
        if row is None:
            raise ValidationFailed(subcode="group_exists")
        _audit(request, cur, principal, "tenant.group_create", row["id"])
    return {"id": row["id"]}


@router.patch("/groups/{group_id}")
def rename_group(
    group_id: str, body: GroupRequest, request: Request, principal: ManageUsers
) -> dict[str, str]:
    group = _id(group_id)
    with _db(request).tenant_tx(principal.tenant_id, principal.user_id) as cur:
        cur.execute(
            "update app.groups set name = %s where id = %s and tenant_id = %s returning id",
            (body.name, group, principal.tenant_id),
        )
        if cur.fetchone() is None:
            raise NotFound()
        _audit(request, cur, principal, "tenant.group_update", group)
    return {"status": "updated"}


@router.delete("/groups/{group_id}")
def delete_group(group_id: str, request: Request, principal: ManageUsers) -> dict[str, str]:
    group = _id(group_id)
    with _db(request).tenant_tx(principal.tenant_id, principal.user_id) as cur:
        cur.execute(
            "delete from app.groups where id = %s and tenant_id = %s returning id",
            (group, principal.tenant_id),
        )
        if cur.fetchone() is None:
            raise NotFound()
        _audit(request, cur, principal, "tenant.group_delete", group)
    return {"status": "deleted"}


@router.post("/groups/{group_id}/members", status_code=201)
def add_member(
    group_id: str, body: MemberRequest, request: Request, principal: ManageUsers
) -> dict[str, str]:
    group, user = _id(group_id), _id(body.user_id)
    with _db(request).tenant_tx(principal.tenant_id, principal.user_id) as cur:
        cur.execute(
            "insert into app.group_members (tenant_id, group_id, user_id) "
            "select %s, g.id, m.user_id from app.groups g join app.memberships m "
            "on m.tenant_id = g.tenant_id where g.id = %s and g.tenant_id = %s and m.user_id = %s "
            "on conflict do nothing returning user_id",
            (principal.tenant_id, group, principal.tenant_id, user),
        )
        if cur.fetchone() is None:
            raise NotFound()  # grupo ou utilizador não são deste tenant (ou já é membro)
        _audit(request, cur, principal, "tenant.group_member_add", group)
    return {"status": "added"}


@router.delete("/groups/{group_id}/members/{user_id}")
def remove_member(
    group_id: str, user_id: str, request: Request, principal: ManageUsers
) -> dict[str, str]:
    group, user = _id(group_id), _id(user_id)
    with _db(request).tenant_tx(principal.tenant_id, principal.user_id) as cur:
        cur.execute(
            "delete from app.group_members where group_id = %s and user_id = %s "
            "and tenant_id = %s returning user_id",
            (group, user, principal.tenant_id),
        )
        if cur.fetchone() is None:
            raise NotFound()
        _audit(request, cur, principal, "tenant.group_member_remove", group)
    return {"status": "removed"}


# ----------------------------------------------------------------------------- definições
class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_retention_days: Literal[0, 30, 90] | None = None
    general_knowledge: Literal["labeled", "forbidden"] | None = None
    redact_pii_for_external: bool | None = None
    block_cloud_for: list[Classification] | None = None
    forced_offline: bool | None = None


@router.get("/settings")
def get_settings(request: Request, principal: ManageSettings) -> dict[str, Any]:
    with _db(request).tenant_tx(principal.tenant_id, principal.user_id) as cur:
        cur.execute("select settings from app.tenants where id = %s", (principal.tenant_id,))
        row = cur.fetchone()
    if row is None:
        raise NotFound()
    stored = row["settings"].get("policy") or {}
    return {key: stored[key] for key in SettingsPatch.model_fields if key in stored}


@router.patch("/settings")
def patch_settings(
    body: SettingsPatch, request: Request, principal: ManageSettings
) -> dict[str, Any]:
    changes = body.model_dump(mode="json", exclude_none=True)
    if not changes:
        raise ValidationFailed(subcode="nothing_to_update")
    with _db(request).tenant_tx(principal.tenant_id, principal.user_id) as cur:
        cur.execute("select settings from app.tenants where id = %s", (principal.tenant_id,))
        row = cur.fetchone()
        if row is None:
            raise NotFound()
        settings = dict(row["settings"])
        policy = {**(settings.get("policy") or {}), **changes}
        settings["policy"] = policy
        cur.execute(
            "update app.tenants set settings = %s::jsonb where id = %s",
            (json.dumps(settings), principal.tenant_id),
        )
        _audit(request, cur, principal, "tenant.settings_update", principal.tenant_id)
    return {key: policy[key] for key in SettingsPatch.model_fields if key in policy}


# ----------------------------------------------------------------------------- auditoria
@router.get("/audit")
def list_audit(
    request: Request,
    principal: ReadAudit,
    action: Annotated[str | None, Query(pattern=r"^[a-z0-9_.]+$")] = None,
    user: Annotated[str | None, Query(max_length=64)] = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    with _db(request).tenant_tx(principal.tenant_id, principal.user_id) as cur:
        cur.execute(
            "select id, actor_type, actor_id, action, resource_type, resource_id, metadata, "
            "created_at from app.audit_log where tenant_id = %s "
            "and (%s::text is null or action = %s) and (%s::text is null or actor_id = %s) "
            "and (%s::timestamptz is null or created_at >= %s) "
            "and (%s::timestamptz is null or created_at <= %s) "
            "order by id desc limit %s offset %s",
            (
                principal.tenant_id,
                action,
                action,
                user,
                user,
                from_,
                from_,
                to,
                to,
                limit + 1,
                offset,
            ),
        )
        rows = cur.fetchall()
    for row in rows:
        row["created_at"] = row["created_at"].isoformat()
    return {"items": rows[:limit], "has_more": len(rows) > limit, "next_offset": offset + limit}
