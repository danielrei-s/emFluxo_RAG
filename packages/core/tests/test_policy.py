"""Testes de ``rag_core.policy`` (C8, INV-01, INV-02, INV-15)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from rag_core.policy import (
    Action,
    acl_matches,
    can,
    can_read,
    can_view_metadata,
    explicit_match,
)
from rag_core.types import (
    AccessFilter,
    Acl,
    ChunkMetadata,
    Classification,
    Origin,
    Principal,
    Role,
)

SHA = "b" * 64
ROLES = (Role.OWNER, Role.ADMIN, Role.EDITOR, Role.MEMBER, Role.VIEWER)


def _flt(role: Role = Role.MEMBER, **overrides: Any) -> AccessFilter:
    fields: dict[str, Any] = {
        "tenant_id": "t1",
        "user_id": "u1",
        "role": role,
        "groups": frozenset({"g1"}),
        "origins": frozenset({Origin.CENTRAL, Origin.LOCAL}),
    }
    fields.update(overrides)
    return AccessFilter(**fields)


def _meta(
    classification: Classification = Classification.INTERNAL,
    acl: Acl | None = None,
    **overrides: Any,
) -> ChunkMetadata:
    fields: dict[str, Any] = {
        "tenant_id": "t1",
        "workspace_id": "w1",
        "doc_id": "d1",
        "source_uri": "upload://d1/a.pdf",
        "content_hash": SHA,
        "doc_hash": SHA,
        "acl": acl if acl is not None else Acl(all_members=True),
        "classification": classification,
        "ingested_at": datetime(2026, 1, 1, tzinfo=UTC),
        "parser_version": "1",
        "origin": Origin.CENTRAL,
    }
    fields.update(overrides)
    return ChunkMetadata(**fields)


ACL_FORMS = {
    "all_members": Acl(all_members=True),
    "user": Acl(users=frozenset({"u1"})),
    "group": Acl(groups=frozenset({"g1"})),
    "none": Acl(users=frozenset({"other"}), groups=frozenset({"other-group"})),
}

T, F = True, False
# Tabela da C8 escrita à mão. Colunas: owner, admin, editor, member, viewer.
READ_TRUTH_TABLE: dict[tuple[Classification, str], tuple[bool, bool, bool, bool, bool]] = {
    # public: qualquer membro do tenant, com ou sem ACL
    (Classification.PUBLIC, "all_members"): (T, T, T, T, T),
    (Classification.PUBLIC, "user"): (T, T, T, T, T),
    (Classification.PUBLIC, "group"): (T, T, T, T, T),
    (Classification.PUBLIC, "none"): (T, T, T, T, T),
    # internal: precisa de corresponder à ACL, qualquer role
    (Classification.INTERNAL, "all_members"): (T, T, T, T, T),
    (Classification.INTERNAL, "user"): (T, T, T, T, T),
    (Classification.INTERNAL, "group"): (T, T, T, T, T),
    (Classification.INTERNAL, "none"): (F, F, F, F, F),
    # confidential: ACL e role >= member (viewer fica de fora)
    (Classification.CONFIDENTIAL, "all_members"): (T, T, T, T, F),
    (Classification.CONFIDENTIAL, "user"): (T, T, T, T, F),
    (Classification.CONFIDENTIAL, "group"): (T, T, T, T, F),
    (Classification.CONFIDENTIAL, "none"): (F, F, F, F, F),
    # restricted: só utilizador/grupo explícitos (all_members não conta), qualquer role
    (Classification.RESTRICTED, "all_members"): (F, F, F, F, F),
    (Classification.RESTRICTED, "user"): (T, T, T, T, T),
    (Classification.RESTRICTED, "group"): (T, T, T, T, T),
    (Classification.RESTRICTED, "none"): (F, F, F, F, F),
}

READ_CASES = [
    (classification, form, role, expected)
    for (classification, form), row in READ_TRUTH_TABLE.items()
    for role, expected in zip(ROLES, row, strict=True)
]


def test_truth_table_has_all_80_cases() -> None:
    assert len(READ_CASES) == 5 * 4 * 4


@pytest.mark.parametrize(("classification", "form", "role", "expected"), READ_CASES)
def test_inv02_read_truth_table(
    classification: Classification, form: str, role: Role, expected: bool
) -> None:
    meta = _meta(classification, ACL_FORMS[form])
    assert can_read(_flt(role), meta) is expected


def test_acl_matches_and_explicit_match() -> None:
    flt = _flt()
    assert acl_matches(flt, ACL_FORMS["all_members"]) is True
    assert acl_matches(flt, ACL_FORMS["user"]) is True
    assert acl_matches(flt, ACL_FORMS["group"]) is True
    assert acl_matches(flt, ACL_FORMS["none"]) is False
    assert explicit_match(flt, ACL_FORMS["all_members"]) is False
    assert explicit_match(flt, ACL_FORMS["user"]) is True
    assert explicit_match(flt, ACL_FORMS["group"]) is True
    assert explicit_match(flt, ACL_FORMS["none"]) is False
    assert acl_matches(flt, Acl()) is False


names = st.sampled_from(["a", "b", "c", "d"])


@given(
    flt_tenant=st.sampled_from(["t1", "t2"]),
    meta_tenant=st.sampled_from(["t1", "t2"]),
    role=st.sampled_from(ROLES),
    classification=st.sampled_from(list(Classification)),
    all_members=st.booleans(),
    users=st.frozensets(names),
    groups=st.frozensets(names),
    user_groups=st.frozensets(names),
    local_only=st.booleans(),
)
def test_inv01_other_tenant_never_readable(
    flt_tenant: str,
    meta_tenant: str,
    role: Role,
    classification: Classification,
    all_members: bool,
    users: frozenset[str],
    groups: frozenset[str],
    user_groups: frozenset[str],
    local_only: bool,
) -> None:
    flt = _flt(role, tenant_id=flt_tenant, user_id="a", groups=user_groups)
    meta = _meta(
        classification,
        Acl(all_members=all_members, users=users, groups=groups),
        tenant_id=meta_tenant,
        local_only=local_only,
    )
    if flt_tenant != meta_tenant:
        assert can_read(flt, meta) is False


@given(
    user_in_users=st.booleans(),
    group_overlap=st.booleans(),
    all_members=st.booleans(),
    role=st.sampled_from(ROLES),
)
def test_explicit_match_implies_acl_match(
    user_in_users: bool, group_overlap: bool, all_members: bool, role: Role
) -> None:
    acl = Acl(
        all_members=all_members,
        users=frozenset({"u1"}) if user_in_users else frozenset(),
        groups=frozenset({"g1"}) if group_overlap else frozenset(),
    )
    flt = _flt(role)
    if explicit_match(flt, acl):
        assert acl_matches(flt, acl)


@pytest.mark.parametrize("role", ROLES)
def test_restricted_requires_explicit_match_even_for_owner(role: Role) -> None:
    flt = _flt(role)
    assert can_read(flt, _meta(Classification.RESTRICTED, Acl(all_members=True))) is False
    assert can_read(flt, _meta(Classification.RESTRICTED, Acl(users=frozenset({"u1"})))) is True
    assert can_read(flt, _meta(Classification.RESTRICTED, Acl(groups=frozenset({"g1"})))) is True


def test_local_only_and_classification_exclusions() -> None:
    meta = _meta(Classification.INTERNAL, local_only=True)
    assert can_read(_flt(), meta) is True
    assert can_read(_flt(exclude_local_only=True), meta) is False
    assert can_read(_flt(exclude_local_only=True), _meta(local_only=False)) is True

    public = _meta(Classification.PUBLIC)
    blocked = _flt(exclude_classifications=frozenset({Classification.PUBLIC}))
    assert can_read(blocked, public) is False
    assert can_read(blocked, _meta(Classification.INTERNAL)) is True
    restricted_blocked = _flt(exclude_classifications=frozenset({Classification.RESTRICTED}))
    explicit = Acl(users=frozenset({"u1"}))
    assert can_read(restricted_blocked, _meta(Classification.RESTRICTED, explicit)) is False


def test_origin_and_workspace_filters() -> None:
    local = _meta(origin=Origin.LOCAL)
    assert can_read(_flt(origins=frozenset({Origin.CENTRAL})), local) is False
    assert can_read(_flt(origins=frozenset({Origin.LOCAL})), local) is True
    assert can_read(_flt(origins=frozenset()), _meta()) is False

    assert can_read(_flt(workspace_ids=None), _meta()) is True
    assert can_read(_flt(workspace_ids=frozenset({"w1"})), _meta()) is True
    assert can_read(_flt(workspace_ids=frozenset({"w2"})), _meta()) is False
    assert can_read(_flt(workspace_ids=frozenset()), _meta()) is False


# --------------------------------------------------------------------------- RBAC

EXPECTED_RBAC: dict[Action, tuple[bool, bool, bool, bool, bool]] = {
    # colunas: owner, admin, editor, member, viewer
    Action.CHAT_USE: (T, T, T, T, T),
    Action.DOC_UPLOAD: (T, T, T, F, F),
    Action.DOC_UPDATE_ACL: (T, T, T, F, F),
    Action.DOC_DELETE: (T, T, T, F, F),
    Action.TENANT_MANAGE_USERS: (T, T, F, F, F),
    Action.TENANT_MANAGE_SETTINGS: (T, T, F, F, F),
    Action.AUDIT_READ: (T, T, F, F, F),
    Action.DEVICE_REVOKE_ANY: (T, T, F, F, F),
    Action.TENANT_EXPORT: (T, F, F, F, F),
    Action.TENANT_DELETE: (T, F, F, F, F),
    Action.DEVICE_REVOKE_OWN: (T, T, T, T, T),
}


def _principal(role: Role, aal: str = "aal2") -> Principal:
    return Principal(tenant_id="t1", user_id="u1", role=role, aal=aal)  # type: ignore[arg-type]


def test_rbac_matrix_covers_every_action() -> None:
    assert set(EXPECTED_RBAC) == set(Action)


@pytest.mark.parametrize("action", list(Action))
def test_rbac_matrix(action: Action) -> None:
    for role, expected in zip(ROLES, EXPECTED_RBAC[action], strict=True):
        assert can(_principal(role), action) is expected, (role, action)


ADMIN_ACTIONS = (
    Action.TENANT_MANAGE_USERS,
    Action.TENANT_MANAGE_SETTINGS,
    Action.AUDIT_READ,
    Action.DEVICE_REVOKE_ANY,
    Action.TENANT_EXPORT,
    Action.TENANT_DELETE,
)


@pytest.mark.parametrize("action", ADMIN_ACTIONS)
def test_inv15_admin_actions_require_aal2(action: Action) -> None:
    assert can(_principal(Role.OWNER, "aal1"), action) is False
    assert can(_principal(Role.ADMIN, "aal1"), action) is False
    assert can(_principal(Role.OWNER, "aal2"), action) is True


@pytest.mark.parametrize("action", [a for a in Action if a not in ADMIN_ACTIONS])
def test_non_admin_actions_do_not_require_aal2(action: Action) -> None:
    assert can(_principal(Role.OWNER, "aal1"), action) is True


def test_can_view_metadata_requires_editor_or_above() -> None:
    expected = {
        Role.OWNER: True,
        Role.ADMIN: True,
        Role.EDITOR: True,
        Role.MEMBER: False,
        Role.VIEWER: False,
    }
    for role, allowed in expected.items():
        assert can_view_metadata(_principal(role)) is allowed
