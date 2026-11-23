"""Testes de F7-T02 (integração): isolamento por tenant nas tabelas de tenancy (INV-01, INV-23)."""

from __future__ import annotations

import psycopg
import pytest
from conftest import TENANT_A, TENANT_B, USER_1, USER_2, USER_3, USER_4, Rls
from psycopg import errors

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

TENANT_TABLES = [
    "tenants", "users", "memberships", "groups", "group_members", "workspaces",
    "tenant_features", "tenant_branding",
]  # fmt: skip
GROUP_B = "22222222-0000-4000-8000-000000000002"
GROUP_A = "11111111-0000-4000-8000-000000000001"

# (tabela, insert que tenta escrever no tenant B, update, delete) — todos com o contexto do tenant A
WRITES: dict[str, tuple[str, str, str]] = {
    "tenants": (
        "insert into app.tenants (slug, name) values ('intruso', 'X')",
        f"update app.tenants set settings = '{{\"x\": 1}}' where id = '{TENANT_B}'",
        f"delete from app.tenants where id = '{TENANT_B}'",
    ),
    "memberships": (
        f"insert into app.memberships (tenant_id, user_id, role) values ('{TENANT_B}', '{USER_4}', 'owner')",
        f"update app.memberships set role = 'viewer' where tenant_id = '{TENANT_B}'",
        f"delete from app.memberships where tenant_id = '{TENANT_B}'",
    ),
    "groups": (
        f"insert into app.groups (tenant_id, name) values ('{TENANT_B}', 'intruso')",
        f"update app.groups set name = 'x' where tenant_id = '{TENANT_B}'",
        f"delete from app.groups where tenant_id = '{TENANT_B}'",
    ),
    "group_members": (
        f"insert into app.group_members (tenant_id, group_id, user_id) values ('{TENANT_B}', '{GROUP_B}', '{USER_4}')",
        f"update app.group_members set user_id = '{USER_4}' where tenant_id = '{TENANT_B}'",
        f"delete from app.group_members where tenant_id = '{TENANT_B}'",
    ),
    "workspaces": (
        f"insert into app.workspaces (tenant_id, name) values ('{TENANT_B}', 'intruso')",
        f"update app.workspaces set name = 'x' where tenant_id = '{TENANT_B}'",
        f"delete from app.workspaces where tenant_id = '{TENANT_B}'",
    ),
    "tenant_features": (
        f"insert into app.tenant_features (tenant_id, feature) values ('{TENANT_B}', 'intruso')",
        f"update app.tenant_features set enabled = false where tenant_id = '{TENANT_B}'",
        f"delete from app.tenant_features where tenant_id = '{TENANT_B}'",
    ),
    "tenant_branding": (
        f"insert into app.tenant_branding (tenant_id, assistant_name) values ('{TENANT_B}', 'x')",
        f"update app.tenant_branding set assistant_name = 'x' where tenant_id = '{TENANT_B}'",
        f"delete from app.tenant_branding where tenant_id = '{TENANT_B}'",
    ),
}


def _count(conn: psycopg.Connection, query: str) -> int:
    row = conn.execute(query.encode("utf-8")).fetchone()  # type: ignore[arg-type]
    assert row is not None
    return int(row[0])


def _blocked(conn: psycopg.Connection, statement: str) -> bool:
    """True se a escrita foi recusada (RLS/privilégio) ou não afetou nenhuma linha."""
    conn.execute("savepoint s")
    try:
        cursor = conn.execute(statement.encode("utf-8"))  # type: ignore[arg-type]
    except (errors.InsufficientPrivilege, errors.UniqueViolation):
        conn.execute("rollback to savepoint s")
        return True
    affected = cursor.rowcount
    conn.execute("rollback to savepoint s")
    return affected == 0


def _admin_count(rls: Rls, query: str) -> int:
    with psycopg.connect(rls.admin_dsn) as conn:
        return _count(conn, query)


def test_inv01_no_tenant_context_sees_nothing(rls: Rls) -> None:
    for context in ({}, {"tenant": ""}, {"user": ""}):
        with rls.connect(**context) as conn:
            for table in TENANT_TABLES:
                assert _count(conn, f"select count(*) from app.{table}") == 0, (table, context)
    with (
        rls.connect(tenant="não-é-um-uuid") as conn,
        pytest.raises(errors.InvalidTextRepresentation),
    ):
        conn.execute("select count(*) from app.tenants")  # contexto inválido nunca devolve dados


@pytest.mark.parametrize("table", sorted(WRITES))
def test_inv01_tenant_a_cannot_read_or_write_b(rls: Rls, table: str) -> None:
    insert, update, delete = WRITES[table]
    other_where = "id" if table == "tenants" else "tenant_id"
    with rls.connect(tenant=TENANT_A, user=USER_1) as conn:
        assert (
            _count(conn, f"select count(*) from app.{table} where {other_where} = '{TENANT_B}'")
            == 0
        )
        assert (
            _count(conn, f"select count(*) from app.{table} where {other_where} = '{TENANT_A}'")
            >= 1
        )
        assert _blocked(conn, insert), f"{table}: insert no tenant B"
        assert _blocked(conn, update), f"{table}: update no tenant B"
        assert _blocked(conn, delete), f"{table}: delete no tenant B"
    # nada mudou para o tenant B (verificado com o superutilizador)
    column = "id" if table == "tenants" else "tenant_id"
    assert _admin_count(rls, f"select count(*) from app.{table} where {column} = '{TENANT_B}'") >= 1


def test_tenant_a_writes_its_own_data(rls: Rls) -> None:
    with rls.connect(tenant=TENANT_A, user=USER_1) as conn:
        conn.execute("insert into app.groups (tenant_id, name) values (%s, 'Suporte')", (TENANT_A,))
        conn.execute(
            "insert into app.workspaces (tenant_id, name) values (%s, 'novo')", (TENANT_A,)
        )
        conn.execute("update app.tenants set settings = '{\"k\": 1}' where id = %s", (TENANT_A,))
        assert _count(conn, "select count(*) from app.groups") == 2
        # uma linha com o tenant errado é recusada pelo WITH CHECK
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("insert into app.groups (tenant_id, name) values (%s, 'x')", (TENANT_B,))


def test_memberships_visible_across_tenants_for_own_user(rls: Rls) -> None:
    with rls.connect(tenant=TENANT_A, user=USER_3) as conn:
        rows = conn.execute("select tenant_id::text, user_id::text from app.memberships").fetchall()
    # a U3 vê os membros do tenant A e as suas próprias pertenças (A e B), mas não a U2 (em B)
    assert (TENANT_B, USER_3) in rows and (TENANT_A, USER_3) in rows and (TENANT_A, USER_1) in rows
    assert (TENANT_B, USER_2) not in rows


def test_users_visible_only_for_self_or_shared_tenant(rls: Rls) -> None:
    with rls.connect(tenant=TENANT_A, user=USER_1) as conn:
        ids = {row[0] for row in conn.execute("select id::text from app.users").fetchall()}
        assert ids == {USER_1, USER_3}  # ela própria e quem está no tenant A
    with (  # membro simples: só pode inserir o próprio
        rls.connect(tenant=TENANT_A, user=USER_3) as conn,
        pytest.raises(errors.InsufficientPrivilege),
    ):
        conn.execute("insert into app.users (id, email) values (gen_random_uuid(), 'x@x.test')")
    with rls.connect(user=USER_4) as conn:  # sem tenant: só ela própria
        assert {r[0] for r in conn.execute("select id::text from app.users").fetchall()} == {USER_4}
        assert _blocked(conn, f"update app.users set display_name = 'x' where id = '{USER_1}'")


def test_tenant_admin_cannot_change_products_or_plan(rls: Rls) -> None:
    with rls.connect(tenant=TENANT_A, user=USER_1) as conn:
        for column, value in (
            ("products", "'{web,local}'"),
            ("plan", "'enterprise'"),
            ("status", "'suspended'"),
            ("slug", "'outro-slug'"),
            ("name", "'Outro'"),
        ):
            conn.execute("savepoint s")
            with pytest.raises(errors.InsufficientPrivilege):
                conn.execute(f"update app.tenants set {column} = {value}".encode())  # type: ignore[arg-type]
            conn.execute("rollback to savepoint s")
        conn.execute('update app.tenants set settings = \'{"tema": "escuro"}\'')  # permitido
        conn.execute("update app.memberships set role = 'editor' where user_id = %s", (USER_3,))
        for statement in (
            f"update app.memberships set tenant_id = '{TENANT_B}' where user_id = '{USER_3}'",
            f"update app.memberships set user_id = '{USER_2}' where user_id = '{USER_3}'",
            f"update app.memberships set products = '{{web}}' where user_id = '{USER_3}'",
        ):
            conn.execute("savepoint s")
            with pytest.raises(errors.InsufficientPrivilege):
                conn.execute(statement.encode())  # type: ignore[arg-type]
            conn.execute("rollback to savepoint s")
    assert _admin_count(rls, "select count(*) from app.tenants where plan = 'pilot'") == 2


def test_platform_staff_not_visible_to_app_user(rls: Rls) -> None:
    for login in ("app_api", "app_worker"):
        with (
            rls.connect(tenant=TENANT_A, user=USER_1, login=login) as conn,
            pytest.raises(errors.InsufficientPrivilege),
        ):
            conn.execute("select * from app.platform_staff")
    with rls.connect(login="app_backoffice") as conn:
        assert _count(conn, "select count(*) from app.platform_staff") == 1


def test_backoffice_reads_all_tenants_metadata_but_cannot_write(rls: Rls) -> None:
    with rls.connect(login="app_backoffice") as conn:
        assert _count(conn, "select count(*) from app.tenants") == 2
        assert _count(conn, "select count(*) from app.memberships") == 4
        for statement in (
            "update app.tenants set plan = 'x'",
            "delete from app.workspaces",
            f"insert into app.groups (tenant_id, name) values ('{TENANT_A}', 'x')",
        ):
            conn.execute("savepoint s")
            with pytest.raises(errors.InsufficientPrivilege):
                conn.execute(statement.encode())  # type: ignore[arg-type]
            conn.execute("rollback to savepoint s")


def test_worker_inherits_user_policies_and_privileges(rls: Rls) -> None:
    with rls.connect(tenant=TENANT_A, user=USER_1, login="app_worker") as conn:
        assert _count(conn, "select count(*) from app.workspaces") == 1
        assert (
            _count(conn, f"select count(*) from app.workspaces where tenant_id = '{TENANT_B}'") == 0
        )


def test_helper_functions(rls: Rls) -> None:
    with rls.connect() as conn:
        row = conn.execute(
            "select app.role_rank('owner'), app.role_rank('viewer'), app.role_rank('x'), "
            "app.classification_rank('public'), app.classification_rank('restricted'), "
            "app.classification_rank('x')"
        ).fetchone()
        assert row == (5, 1, 0, 0, 3, 99)
        assert conn.execute("select app.current_tenant(), app.current_user_id()").fetchone() == (
            None,
            None,
        )
    with rls.connect(tenant=TENANT_A, user=USER_1) as conn:
        assert conn.execute("select app.current_tenant()::text").fetchone() == (TENANT_A,)
