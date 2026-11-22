"""Testes de F7-T01 (integração, Postgres real): migrações, roles e extensões (INV-01)."""

from __future__ import annotations

import shutil
from pathlib import Path

import psycopg
import pytest
from db_bootstrap_roles import LOGINS, bootstrap
from db_migrate import MIGRATIONS_DIR, MigrationError, discover, migrate

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
ALL_FILES = [m.filename for m in discover()]
PASSWORDS = {login: f"pw-{login}-x9" for login in LOGINS}


def _scalar(dsn: str, query: str) -> object:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(query.encode("utf-8")).fetchone()  # type: ignore[arg-type]
    return row[0] if row else None


def test_migrate_from_empty_and_idempotent(db: str) -> None:
    assert migrate(db, dry_run=True) == ALL_FILES
    assert _scalar(db, "select to_regclass('app_meta.schema_migrations')") is None  # dry-run
    assert migrate(db) == ALL_FILES
    assert migrate(db) == []  # idempotente
    assert _scalar(db, "select count(*) from app_meta.schema_migrations") == len(ALL_FILES)
    schemas = _scalar(
        db, "select count(*) from pg_namespace where nspname in ('app','app_meta','extensions')"
    )
    assert schemas == 3
    # as roles existem mesmo que se volte a aplicar o SQL à mão (idempotência do próprio ficheiro)
    sql = (MIGRATIONS_DIR / "0001_schemas_roles_extensions.sql").read_text(encoding="utf-8")
    with psycopg.connect(db, autocommit=True) as conn:
        conn.execute(sql.encode("utf-8"))  # type: ignore[arg-type]


def test_checksum_tamper_detected(db: str, tmp_path: Path) -> None:
    copy = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, copy)
    migrate(db, copy)
    target = copy / "0001_schemas_roles_extensions.sql"
    target.write_text(target.read_text(encoding="utf-8") + "\n-- alterado\n", encoding="utf-8")
    with pytest.raises(MigrationError, match="checksum_mismatch:0001"):
        migrate(db, copy)


def test_failed_migration_rolls_back_and_is_not_recorded(db: str, tmp_path: Path) -> None:
    copy = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, copy)
    (copy / f"{len(ALL_FILES) + 1:04d}_broken.sql").write_text(
        "create table app.t (id int);\nselect 1/0;\n", encoding="utf-8"
    )
    with pytest.raises(psycopg.errors.DivisionByZero):
        migrate(db, copy)
    assert _scalar(db, "select to_regclass('app.t')") is None
    assert _scalar(db, "select count(*) from app_meta.schema_migrations") == len(ALL_FILES)


def test_inv01_app_roles_have_no_bypassrls(db: str) -> None:
    migrate(db)
    assert bootstrap(db, PASSWORDS) == list(LOGINS)
    bootstrap(db, PASSWORDS)  # voltar a correr só atualiza as passwords
    rows = (
        psycopg.connect(db)
        .execute(
            "select rolname, rolbypassrls, rolsuper, rolcanlogin from pg_roles "
            "where rolname like 'app\\_%' order by rolname"
        )
        .fetchall()
    )
    names = {name for name, *_ in rows}
    assert names == {
        "app_user_role", "app_worker_role", "app_backoffice_role", *LOGINS,
    }  # fmt: skip
    assert all(not bypass and not superuser for _, bypass, superuser, _ in rows)
    assert {n for n, *_, login in rows if login} == set(LOGINS)
    path = _scalar(db, "select rolconfig::text from pg_roles where rolname = 'app_api'")
    assert "search_path=app, extensions, public" in str(path)
    members = (
        psycopg.connect(db)
        .execute(
            "select pg_has_role('app_worker', 'app_user_role', 'usage'), "
            "pg_has_role('app_api', 'app_worker_role', 'member'), "
            "pg_has_role('app_api', 'app_user_role', 'usage')"
        )
        .fetchone()
    )
    # os logins herdam os privilégios da sua role de grupo; a API não é membro da do worker
    assert members == (True, False, True)


def test_bootstrap_requires_every_password(db: str) -> None:
    migrate(db)
    with pytest.raises(ValueError, match="missing_passwords:app_worker"):
        bootstrap(db, {**PASSWORDS, "app_worker": ""})


def test_anon_and_authenticated_have_no_access_to_app_schema(db: str) -> None:
    migrate(db)
    for role in ("anon", "authenticated", "app_api_inexistente_public"):
        if role.startswith("app_api"):
            continue
        usage = _scalar(db, f"select has_schema_privilege('{role}', 'app', 'USAGE')")
        create = _scalar(db, f"select has_schema_privilege('{role}', 'app', 'CREATE')")
        assert (usage, create) == (False, False), role
    assert _scalar(db, "select has_schema_privilege('public', 'app', 'USAGE')") is False
    assert _scalar(db, "select has_schema_privilege('app_user_role', 'app', 'USAGE')") is True


def test_vector_extension_in_extensions_schema(db: str) -> None:
    migrate(db)
    where = _scalar(
        db, "select extnamespace::regnamespace::text from pg_extension where extname='vector'"
    )
    assert where == "extensions"
    unaccent = _scalar(
        db, "select extnamespace::regnamespace::text from pg_extension where extname='unaccent'"
    )
    assert unaccent == "extensions"
    dim = _scalar(db, "select extensions.vector_dims('[1,2,3]'::extensions.vector)")
    assert dim == 3
