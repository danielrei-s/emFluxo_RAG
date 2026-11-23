"""Testes de F7-T03 (integração): contexto de tenant na transação e sem fugas (INV-01)."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import TENANT_A, TENANT_B, USER_1, USER_2, Rls
from rag_central.db import Database, make_pool
from rag_core.errors import AccessDenied, ValidationFailed

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def database(rls: Rls) -> Iterator[Database]:
    pool = make_pool(
        rls.dsn_for("app_api"), min_size=1, max_size=1
    )  # 1 ligação: força a reutilização
    pool.open(wait=True)
    try:
        yield Database(pool)
    finally:
        pool.close()


def test_tenant_context_set_inside_transaction(database: Database) -> None:
    with database.tenant_tx(TENANT_A, USER_1) as cur:
        cur.execute(
            "select current_setting('app.tenant_id') as t, current_setting('app.user_id') as u"
        )
        assert cur.fetchone() == {"t": TENANT_A, "u": USER_1}
        cur.execute("select count(*) as n from app.workspaces")
        assert cur.fetchone() == {"n": 1}  # só os do tenant A
    with database.tenant_tx(TENANT_B) as cur:  # sem utilizador
        cur.execute(
            "select app.current_user_id() as u, count(*) as n from app.workspaces group by 1"
        )
        assert cur.fetchone() == {"u": None, "n": 1}


def test_inv01_tenant_context_does_not_leak_between_requests(database: Database) -> None:
    with database.tenant_tx(TENANT_A, USER_1) as cur:
        cur.execute("select 1")
    # a mesma ligação (pool de 1) volta sem contexto
    with database._pool.connection() as conn:
        value = conn.execute("select current_setting('app.tenant_id', true) as t").fetchone()
        assert value == {"t": ""} or value == {"t": None}
        assert conn.execute("select count(*) as n from app.tenants").fetchone() == {"n": 0}


def test_context_is_rolled_back_with_the_transaction(database: Database) -> None:
    with pytest.raises(RuntimeError), database.tenant_tx(TENANT_A, USER_1) as cur:
        cur.execute("insert into app.workspaces (tenant_id, name) values (%s, 'temp')", (TENANT_A,))
        raise RuntimeError("falha")
    with database.tenant_tx(TENANT_A) as cur:
        cur.execute("select count(*) as n from app.workspaces where name = 'temp'")
        assert cur.fetchone() == {"n": 0}


def test_concurrent_threads_different_tenants_isolated(rls: Rls) -> None:
    pool = make_pool(rls.dsn_for("app_api"), min_size=4, max_size=4)
    pool.open(wait=True)
    database = Database(pool)
    seen: dict[str, set[str]] = {}
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def work(tenant: str, user: str) -> None:
        try:
            barrier.wait(timeout=10)
            names: set[str] = set()
            for _ in range(50):
                with database.tenant_tx(tenant, user) as cur:
                    cur.execute("select tenant_id::text as t from app.workspaces")
                    names |= {row["t"] for row in cur.fetchall()}
            seen[tenant] = names
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=work, args=(TENANT_A, USER_1)),
        threading.Thread(target=work, args=(TENANT_B, USER_2)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    pool.close()
    assert errors == []
    assert seen == {TENANT_A: {TENANT_A}, TENANT_B: {TENANT_B}}


def test_invalid_context_is_rejected_before_touching_the_db(database: Database) -> None:
    for tenant, user in (("x", None), (TENANT_A, "x"), ("'; drop table app.tenants; --", None)):
        with pytest.raises(ValidationFailed), database.tenant_tx(tenant, user):
            pass


def test_system_tx_is_not_available_to_the_api(rls: Rls, database: Database) -> None:
    with pytest.raises(AccessDenied), database.system_tx("job_claim"):
        pass
    pool = make_pool(rls.dsn_for("app_worker"), min_size=1, max_size=1)
    pool.open(wait=True)
    worker = Database(pool, allow_system=True)
    with worker.system_tx("job_claim") as cur:
        cur.execute("select count(*) as n from app.tenants")
        assert cur.fetchone() == {"n": 0}  # sem contexto de tenant o RLS não deixa ver nada
    with pytest.raises(ValidationFailed), worker.system_tx("porque-sim"):
        pass
    pool.close()


def test_no_cursor_execute_outside_tenant_or_system_tx() -> None:
    """DoD: na Central API só ``db.py`` abre ligações; os repositórios recebem um cursor."""
    source = ROOT / "services" / "central-api" / "rag_central"
    offenders = []
    for path in source.rglob("*.py"):
        if path.name == "db.py":
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"\.connection\(|psycopg\.connect\(|\.getconn\(", text):
            offenders.append(path.name)
    assert offenders == []
    db_text = (source / "db.py").read_text(encoding="utf-8")
    assert (
        db_text.count("self._pool.connection()") == 5
    )  # tenant_tx, user_tx, public_tx, ping e system_tx
