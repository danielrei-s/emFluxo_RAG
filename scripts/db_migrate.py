"""Aplica as migrações SQL numeradas de ``infra/db/migrations`` (F7-T01).

    uv run python scripts/db_migrate.py [--dry-run]

Usa ``RAG_DATABASE_MIGRATOR_URL``. Cada ficheiro corre numa transação; o checksum (SHA-256 com
fins de linha normalizados) de um ficheiro já aplicado não pode mudar. Só imprime versões e nomes
de ficheiros, nunca o URL (que contém credenciais).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "infra" / "db" / "migrations"
_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
LOCK_ID = 7_420_001  # advisory lock: duas migrações em simultâneo não se atropelam

BOOTSTRAP_SQL = """
create schema if not exists app_meta;
create table if not exists app_meta.schema_migrations (
  version text primary key,
  checksum text not null,
  applied_at timestamptz not null default now()
);
"""


class MigrationError(Exception):
    """Erro de migração; a mensagem é só um código e um nome de ficheiro."""


@dataclass(frozen=True)
class Migration:
    version: str
    filename: str
    sql: str
    checksum: str


def checksum_of(sql: str) -> str:
    return hashlib.sha256(sql.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Ficheiros ``NNNN_nome.sql`` por ordem de versão; as versões não se repetem."""
    found: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = _NAME.match(path.name)
        if match is None:
            raise MigrationError(f"invalid_filename:{path.name}")
        sql = path.read_text(encoding="utf-8")
        found.append(Migration(match.group(1), path.name, sql, checksum_of(sql)))
    versions = [m.version for m in found]
    if len(set(versions)) != len(versions):
        raise MigrationError("duplicate_versions")  # lacunas são aceites (migrações adiadas)
    return found


def migrate(dsn: str, directory: Path = MIGRATIONS_DIR, *, dry_run: bool = False) -> list[str]:
    """Aplica as migrações pendentes e devolve os ficheiros aplicados (ou que o seriam)."""
    migrations = discover(directory)
    applied: list[str] = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("select pg_advisory_lock(%s)", (LOCK_ID,))
        try:
            if not dry_run:
                conn.execute(BOOTSTRAP_SQL.encode("utf-8"))  # type: ignore[arg-type]
            done = _already_applied(conn)
            for migration in migrations:
                known = done.get(migration.version)
                if known is not None:
                    if known != migration.checksum:
                        raise MigrationError(f"checksum_mismatch:{migration.filename}")
                    continue
                applied.append(migration.filename)
                if not dry_run:
                    _apply(conn, migration)
        finally:
            conn.execute("select pg_advisory_unlock(%s)", (LOCK_ID,))
    return applied


def _already_applied(conn: psycopg.Connection) -> dict[str, str]:
    exists = conn.execute("select to_regclass('app_meta.schema_migrations')").fetchone()
    if not exists or exists[0] is None:
        return {}
    rows = conn.execute("select version, checksum from app_meta.schema_migrations").fetchall()
    return {str(version): str(checksum) for version, checksum in rows}


def _apply(conn: psycopg.Connection, migration: Migration) -> None:
    with conn.transaction():
        conn.execute(migration.sql.encode("utf-8"))  # type: ignore[arg-type]
        conn.execute(
            "insert into app_meta.schema_migrations (version, checksum) values (%s, %s)",
            (migration.version, migration.checksum),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="só lista o que seria aplicado")
    args = parser.parse_args(argv)

    from rag_core.config import Settings

    url = Settings.from_env().database_migrator_url
    if url is None:
        print("erro: RAG_DATABASE_MIGRATOR_URL não está definido", file=sys.stderr)
        return 2
    try:
        applied = migrate(url.get_secret_value(), dry_run=args.dry_run)
    except MigrationError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"erro: {type(exc).__name__}", file=sys.stderr)  # sem a mensagem (pode ter o URL)
        return 1
    verb = "seriam aplicadas" if args.dry_run else "aplicadas"
    print(f"{len(applied)} migração(ões) {verb}: {', '.join(applied) or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
