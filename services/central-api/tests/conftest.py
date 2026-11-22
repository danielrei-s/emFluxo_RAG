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


# ----------------------------------------------------------------------- RLS (F7-T02 em diante)
PASSWORDS = {"app_api": "pw-api-1", "app_worker": "pw-worker-1", "app_backoffice": "pw-bo-1"}
TENANT_A = "aaaaaaaa-0000-4000-8000-00000000000a"
TENANT_B = "bbbbbbbb-0000-4000-8000-00000000000b"
USER_1, USER_2, USER_3, USER_4 = (f"00000000-0000-4000-8000-00000000000{i}" for i in range(1, 5))


class Rls:
    """Base com todas as migrações, utilizadores de aplicação e dados de dois tenants."""

    def __init__(self, admin_dsn: str) -> None:
        self.admin_dsn = admin_dsn

    def dsn_for(self, login: str) -> str:
        from psycopg.conninfo import conninfo_to_dict, make_conninfo

        info = conninfo_to_dict(self.admin_dsn)
        return make_conninfo(user=login, password=PASSWORDS[login], **{
            k: v for k, v in info.items() if k not in {"user", "password"}
        })  # fmt: skip

    def connect(
        self,
        tenant: str | None = None,
        user: str | None = None,
        login: str = "app_api",
    ) -> psycopg.Connection:
        """Ligação como utilizador de aplicação com o contexto de tenant da transação."""
        conn = psycopg.connect(self.dsn_for(login))
        if tenant is not None or user is not None:
            conn.execute(
                "select set_config('app.tenant_id', %s, true), set_config('app.user_id', %s, true)",
                (tenant or "", user or ""),
            )
        return conn


@pytest.fixture
def rls(db: str) -> Rls:
    from db_bootstrap_roles import bootstrap
    from db_migrate import migrate

    migrate(db)
    bootstrap(db, PASSWORDS)
    sql = """
            insert into app.tenants (id, slug, name, products) values
              (%s, 'aurora', 'Aurora', '{web}'), (%s, 'boreal', 'Boreal', '{web,local}');
            insert into app.users (id, email) values
              (%s, 'u1@a.test'), (%s, 'u2@b.test'), (%s, 'u3@ab.test'), (%s, 'u4@x.test');
            insert into app.memberships (tenant_id, user_id, role) values
              (%s, %s, 'admin'), (%s, %s, 'member'), (%s, %s, 'member'), (%s, %s, 'editor');
            insert into app.groups (id, tenant_id, name) values
              ('11111111-0000-4000-8000-000000000001', %s, 'Vendas'),
              ('22222222-0000-4000-8000-000000000002', %s, 'Vendas');
            insert into app.group_members (tenant_id, group_id, user_id) values
              (%s, '11111111-0000-4000-8000-000000000001', %s),
              (%s, '22222222-0000-4000-8000-000000000002', %s);
            insert into app.workspaces (tenant_id, name) values (%s, 'wa'), (%s, 'wb');
            insert into app.tenant_features (tenant_id, feature, enabled) values
              (%s, 'chat', true), (%s, 'chat', true);
            insert into app.tenant_branding (tenant_id, assistant_name) values (%s, 'A'), (%s, 'B');
            insert into app.platform_staff (user_id, role) values (%s, 'admin');
            """
    params = (
        TENANT_A,
        TENANT_B,
        USER_1,
        USER_2,
        USER_3,
        USER_4,
        TENANT_A,
        USER_1,
        TENANT_B,
        USER_2,
        TENANT_A,
        USER_3,
        TENANT_B,
        USER_3,
        TENANT_A,
        TENANT_B,
        TENANT_A,
        USER_1,
        TENANT_B,
        USER_2,
        TENANT_A,
        TENANT_B,
        TENANT_A,
        TENANT_B,
        TENANT_A,
        TENANT_B,
        USER_4,
    )
    with psycopg.connect(db, autocommit=True) as conn:  # superutilizador: ignora o RLS
        remaining = list(params)
        for statement in (part.strip() for part in sql.split(";") if part.strip()):
            count = statement.count("%s")
            conn.execute(statement.encode(), remaining[:count])  # type: ignore[arg-type]
            remaining = remaining[count:]
    return Rls(db)
