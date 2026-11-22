"""Fixtures de BD (marcador ``integration``): Postgres real com pgvector em testcontainers.

``pg`` é um contentor por sessão; ``db`` dá a cada teste uma base de dados nova (os roles são do
cluster, por isso as migrações têm de ser idempotentes e os testes não dependem de dados antigos).
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

IMAGE = "pgvector/pgvector:0.8.7-pg17"  # a mesma do compose de desenvolvimento


class PgCluster:
    """Liga-se ao cluster como superutilizador e cria bases de dados descartáveis."""

    def __init__(self, host: str, port: int, user: str, password: str) -> None:
        self._base = f"postgresql://{user}:{password}@{host}:{port}"
        self.user, self.password, self.host, self.port = user, password, host, port

    def dsn(self, dbname: str, user: str | None = None, password: str | None = None) -> str:
        user = user or self.user
        password = password or self.password
        return f"postgresql://{user}:{password}@{self.host}:{self.port}/{dbname}"

    def create_database(self) -> str:
        name = f"t_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(self.dsn("postgres"), autocommit=True) as conn:
            conn.execute(f'create database "{name}"')
        return name


@pytest.fixture(scope="session")
def pg() -> Iterator[PgCluster]:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(IMAGE, username="postgres", password="postgres", dbname="postgres") as c:
        yield PgCluster(
            c.get_container_host_ip(), int(c.get_exposed_port(5432)), "postgres", "postgres"
        )


@pytest.fixture
def db(pg: PgCluster) -> str:
    """DSN (superutilizador) de uma base de dados vazia, com ``anon`` e ``authenticated``."""
    with psycopg.connect(pg.dsn("postgres"), autocommit=True) as conn:
        for role in ("anon", "authenticated"):  # imita o Supabase
            conn.execute(
                f"do $$ begin if not exists (select 1 from pg_roles where rolname='{role}') "
                f"then create role {role} nologin; end if; end $$"
            )
    return pg.dsn(pg.create_database())
