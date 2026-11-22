"""Cria (ou atualiza a password de) os utilizadores de aplicação da BD central (F7-T01).

    uv run python scripts/db_bootstrap_roles.py

Corre com ``RAG_DATABASE_MIGRATOR_URL`` e lê as passwords do ambiente
(``RAG_DB_API_PASSWORD``, ``RAG_DB_WORKER_PASSWORD``, ``RAG_DB_BACKOFFICE_PASSWORD``). As passwords
nunca são impressas. Os utilizadores nunca têm BYPASSRLS nem SUPERUSER (INV-01).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

import psycopg
from psycopg import sql

# utilizador de login -> (role de grupo, variável de ambiente com a password)
LOGINS: dict[str, tuple[str, str]] = {
    "app_api": ("app_user_role", "RAG_DB_API_PASSWORD"),
    "app_worker": ("app_worker_role", "RAG_DB_WORKER_PASSWORD"),
    "app_backoffice": ("app_backoffice_role", "RAG_DB_BACKOFFICE_PASSWORD"),
}
SEARCH_PATH = "app, extensions, public"


def bootstrap(dsn: str, passwords: Mapping[str, str]) -> list[str]:
    """``passwords`` mapeia o utilizador de login para a password. Devolve os utilizadores."""
    missing = [login for login in LOGINS if not passwords.get(login)]
    if missing:
        raise ValueError(f"missing_passwords:{','.join(missing)}")
    with psycopg.connect(dsn, autocommit=True) as conn:
        for login, (group, _) in LOGINS.items():
            name = sql.Identifier(login)
            exists = conn.execute("select 1 from pg_roles where rolname = %s", (login,)).fetchone()
            verb = sql.SQL("alter" if exists else "create")
            # SQL composto só com psycopg.sql (identificadores e literais escapados).
            # nosemgrep: sqlalchemy-execute-raw-query
            conn.execute(
                sql.SQL(
                    "{} role {} with login nosuperuser nobypassrls nocreatedb nocreaterole "
                    "inherit password {}"
                ).format(verb, name, sql.Literal(passwords[login]))
            )
            # nosemgrep: sqlalchemy-execute-raw-query
            conn.execute(sql.SQL("grant {} to {}").format(sql.Identifier(group), name))
            # nosemgrep: sqlalchemy-execute-raw-query
            conn.execute(
                sql.SQL("alter role {} set search_path = {}").format(name, sql.SQL(SEARCH_PATH))
            )
    return list(LOGINS)


def main() -> int:
    from rag_core.config import Settings

    url = Settings.from_env().database_migrator_url
    if url is None:
        print("erro: RAG_DATABASE_MIGRATOR_URL não está definido", file=sys.stderr)
        return 2
    passwords = {login: os.environ.get(var, "") for login, (_, var) in LOGINS.items()}
    try:
        names = bootstrap(url.get_secret_value(), passwords)
    except ValueError as exc:
        print(f"erro: {exc}", file=sys.stderr)  # só os nomes das passwords em falta
        return 2
    except psycopg.Error as exc:
        print(f"erro: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"utilizadores prontos: {', '.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
