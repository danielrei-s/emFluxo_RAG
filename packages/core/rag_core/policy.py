"""Política de acesso (C8): funções puras, referência para todos os filtros.

Os filtros de cada ``VectorStore`` (memória, SQLite, Postgres) têm de dar o mesmo resultado que
``can_read`` (INV-02). Nenhuma decisão de acesso é delegada ao LLM.
"""

from __future__ import annotations

from enum import StrEnum

from rag_core.types import (
    ROLE_RANK,
    AccessFilter,
    Acl,
    ChunkMetadata,
    Classification,
    Principal,
    Role,
)


class Action(StrEnum):
    """Ações sujeitas a RBAC."""

    CHAT_USE = "chat.use"
    DOC_UPLOAD = "doc.upload"
    DOC_UPDATE_ACL = "doc.update_acl"
    DOC_DELETE = "doc.delete"
    TENANT_MANAGE_USERS = "tenant.manage_users"
    TENANT_MANAGE_SETTINGS = "tenant.manage_settings"
    AUDIT_READ = "audit.read"
    DEVICE_REVOKE_ANY = "device.revoke_any"
    DEVICE_REVOKE_OWN = "device.revoke_own"
    TENANT_EXPORT = "tenant.export"
    TENANT_DELETE = "tenant.delete"


_ALL_ROLES = frozenset(Role)
_EDITOR_UP = frozenset({Role.OWNER, Role.ADMIN, Role.EDITOR})
_ADMIN_UP = frozenset({Role.OWNER, Role.ADMIN})
_OWNER_ONLY = frozenset({Role.OWNER})

_RBAC: dict[Action, frozenset[Role]] = {
    Action.CHAT_USE: _ALL_ROLES,
    Action.DOC_UPLOAD: _EDITOR_UP,
    Action.DOC_UPDATE_ACL: _EDITOR_UP,
    Action.DOC_DELETE: _EDITOR_UP,
    Action.TENANT_MANAGE_USERS: _ADMIN_UP,
    Action.TENANT_MANAGE_SETTINGS: _ADMIN_UP,
    Action.AUDIT_READ: _ADMIN_UP,
    Action.DEVICE_REVOKE_ANY: _ADMIN_UP,
    Action.TENANT_EXPORT: _OWNER_ONLY,
    Action.TENANT_DELETE: _OWNER_ONLY,
    Action.DEVICE_REVOKE_OWN: _ALL_ROLES,
}

#: Ações de administração: exigem autenticação forte ``aal2`` (INV-15).
ADMIN_ACTIONS: frozenset[Action] = frozenset(
    {
        Action.TENANT_MANAGE_USERS,
        Action.TENANT_MANAGE_SETTINGS,
        Action.AUDIT_READ,
        Action.DEVICE_REVOKE_ANY,
        Action.TENANT_EXPORT,
        Action.TENANT_DELETE,
    }
)


def explicit_match(flt: AccessFilter, acl: Acl) -> bool:
    """O utilizador, ou um grupo seu, está explicitamente na ACL (``all_members`` não conta)."""
    return flt.user_id in acl.users or not flt.groups.isdisjoint(acl.groups)


def acl_matches(flt: AccessFilter, acl: Acl) -> bool:
    """Corresponde à ACL: ``all_members`` ou correspondência explícita."""
    return acl.all_members or explicit_match(flt, acl)


def can_read(flt: AccessFilter, meta: ChunkMetadata) -> bool:
    """Indica se o filtro pode ler o conteúdo de um chunk com estes metadados (C8)."""
    if meta.tenant_id != flt.tenant_id:  # INV-01
        return False
    if meta.origin not in flt.origins:
        return False
    if flt.exclude_local_only and meta.local_only:
        return False
    if meta.classification in flt.exclude_classifications:
        return False
    if flt.workspace_ids is not None and meta.workspace_id not in flt.workspace_ids:
        return False

    match meta.classification:
        case Classification.PUBLIC:
            return True
        case Classification.INTERNAL:
            return acl_matches(flt, meta.acl)
        case Classification.CONFIDENTIAL:
            return acl_matches(flt, meta.acl) and ROLE_RANK[flt.role] >= ROLE_RANK[Role.MEMBER]
        case Classification.RESTRICTED:
            return explicit_match(flt, meta.acl)


def can(principal: Principal, action: Action) -> bool:
    """RBAC da C8; as ações de administração exigem ``aal2`` (INV-15)."""
    if principal.role not in _RBAC[action]:
        return False
    return not (action in ADMIN_ACTIONS and principal.aal != "aal2")


def can_view_metadata(principal: Principal) -> bool:
    """Metadados (sem conteúdo) de todos os documentos do tenant: role ≥ editor."""
    return ROLE_RANK[principal.role] >= ROLE_RANK[Role.EDITOR]
