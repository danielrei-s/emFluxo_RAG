"""Testes de catálogo (integração): INV-01 em **todas** as tabelas do schema ``app``.

Este ficheiro corre a cada migração futura: uma tabela nova sem RLS forçado falha aqui.
"""

from __future__ import annotations

import psycopg
import pytest
from conftest import Rls

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

# Tabelas sem RLS (têm de estar sem qualquer grant para as roles da aplicação).
NO_RLS_ALLOWLIST = {"platform_staff"}
APP_ROLES = ("app_user_role", "app_worker_role", "anon", "authenticated")


def _tables(rls: Rls) -> list[tuple[str, bool, bool]]:
    with psycopg.connect(rls.admin_dsn) as conn:
        return [
            (str(name), bool(enabled), bool(forced))
            for name, enabled, forced in conn.execute(
                "select c.relname, c.relrowsecurity, c.relforcerowsecurity "
                "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                "where n.nspname = 'app' and c.relkind in ('r', 'p') order by 1"
            ).fetchall()
        ]


def test_inv01_all_app_tables_have_rls_forced(rls: Rls) -> None:
    tables = _tables(rls)
    assert len(tables) >= 9
    missing = [
        name for name, enabled, forced in tables
        if name not in NO_RLS_ALLOWLIST and not (enabled and forced)
    ]  # fmt: skip
    assert missing == [], f"tabelas sem RLS forçado: {missing}"
    assert {name for name, *_ in tables} >= NO_RLS_ALLOWLIST


def test_every_rls_table_has_at_least_one_policy(rls: Rls) -> None:
    with psycopg.connect(rls.admin_dsn) as conn:
        without = conn.execute(
            "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'app' and c.relkind = 'r' and c.relrowsecurity "
            "and not exists (select 1 from pg_policy p where p.polrelid = c.oid)"
        ).fetchall()
    assert without == []  # RLS sem políticas bloqueia tudo: quase de certeza um esquecimento


def test_no_policy_applies_to_public_or_supabase_roles(rls: Rls) -> None:
    with psycopg.connect(rls.admin_dsn) as conn:
        rows = conn.execute(
            "select c.relname, p.polname, pg_get_userbyid(r) from pg_policy p "
            "join pg_class c on c.oid = p.polrelid, unnest(p.polroles) as r "
            "where c.relnamespace = 'app'::regnamespace and (r = 0 or pg_get_userbyid(r) in "
            "('anon', 'authenticated', 'public'))"
        ).fetchall()
        # polroles = {0} significa PUBLIC
    assert rows == []


def test_app_roles_only_get_explicit_grants_and_never_on_staff(rls: Rls) -> None:
    with psycopg.connect(rls.admin_dsn) as conn:
        for name, *_ in _tables(rls):
            for role in ("anon", "authenticated", "public"):
                privileges = conn.execute(
                    "select has_table_privilege(%s, %s, p) from unnest(array['SELECT', 'INSERT', "
                    "'UPDATE', 'DELETE']) as p"
                    if role != "public"
                    else "select false",
                    (role, f"app.{name}") if role != "public" else (),
                ).fetchall()
                assert not any(v for (v,) in privileges), (name, role)
        for role in ("app_user_role", "app_worker_role"):
            assert conn.execute(
                "select has_table_privilege(%s, 'app.platform_staff', 'SELECT')", (role,)
            ).fetchone() == (False,)


def test_inv23_backoffice_has_no_write_privileges(rls: Rls) -> None:
    with psycopg.connect(rls.admin_dsn) as conn:
        for name, *_ in _tables(rls):
            writes = conn.execute(
                "select bool_or(has_table_privilege('app_backoffice_role', %s, p)) "
                "from unnest(array['INSERT', 'UPDATE', 'DELETE']) as p",
                (f"app.{name}",),
            ).fetchone()
            assert writes == (False,), name
