"""Testes de F7-T06 (integração): auditoria append-only com cadeia de hashes (INV-03, INV-16)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg
import pytest
from conftest import TENANT_A, TENANT_B, USER_1, Rls
from psycopg import errors
from rag_central.audit import GENESIS, AuditLogger, verify_chain
from rag_central.db import Database, make_pool
from rag_core.clock import FakeClock
from rag_core.errors import ValidationFailed

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
CLOCK = FakeClock(datetime(2026, 5, 10, 12, 0, 0, 123456, tzinfo=UTC))


@pytest.fixture
def database(rls: Rls) -> Iterator[Database]:
    pool = make_pool(rls.dsn_for("app_api"), max_size=6)
    pool.open(wait=True)
    yield Database(pool)
    pool.close()


def _record(database: Database, audit: AuditLogger, tenant: str, n: int = 1) -> None:
    for i in range(n):
        CLOCK.advance(1)
        with database.tenant_tx(tenant, USER_1) as cur:
            audit.record(
                cur, tenant_id=tenant, actor_type="user", actor_id=USER_1, action="doc.upload",
                resource_type="document", resource_id=f"d{i}", metadata={"count": i, "status": "ok"},
            )  # fmt: skip


def _valid(database: Database, tenant: str) -> bool:
    with database.tenant_tx(tenant, USER_1) as cur:
        return verify_chain(cur, tenant)


def test_chain_valid_after_many_inserts(database: Database) -> None:
    audit = AuditLogger(CLOCK)
    assert _valid(database, TENANT_A)  # cadeia vazia
    _record(database, audit, TENANT_A, 25)
    _record(database, audit, TENANT_B, 3)
    assert _valid(database, TENANT_A) and _valid(database, TENANT_B)
    with database.tenant_tx(TENANT_A, USER_1) as cur:
        cur.execute("select prev_hash, hash from app.audit_log order by id limit 2")
        first, second = cur.fetchall()
    assert first["prev_hash"] == GENESIS and second["prev_hash"] == first["hash"]
    with database.tenant_tx(TENANT_A, USER_1) as cur:  # o tenant A não vê a auditoria do B
        cur.execute("select count(*) as n from app.audit_log")
        assert cur.fetchone() == {"n": 25}


def test_inv16_update_and_delete_rejected(database: Database, rls: Rls) -> None:
    _record(database, AuditLogger(CLOCK), TENANT_A, 2)
    with database.tenant_tx(TENANT_A, USER_1) as cur:
        for statement in (
            "update app.audit_log set action = 'x'",
            "delete from app.audit_log",
            "truncate app.audit_log",
        ):
            cur.execute("savepoint s")
            with pytest.raises(errors.InsufficientPrivilege):  # sem privilégio ou pelo trigger
                cur.execute(statement.encode())  # type: ignore[arg-type]
            cur.execute("rollback to savepoint s")
    with psycopg.connect(rls.admin_dsn) as conn:  # nem o superutilizador, graças ao trigger
        for statement in ("update app.audit_log set action = 'x'", "delete from app.audit_log"):
            with pytest.raises(errors.InsufficientPrivilege, match="append-only"):
                conn.execute(statement.encode())  # type: ignore[arg-type]
            conn.rollback()
        with pytest.raises(errors.InsufficientPrivilege, match="append-only"):
            conn.execute("truncate app.audit_log")


def test_inv16_tamper_detected(database: Database, rls: Rls) -> None:
    _record(database, AuditLogger(CLOCK), TENANT_A, 5)
    assert _valid(database, TENANT_A)
    with psycopg.connect(rls.admin_dsn, autocommit=True) as conn:  # papel de migração
        conn.execute("alter table app.audit_log disable trigger audit_no_update")
        conn.execute(
            "update app.audit_log set action = 'doc.delete' where id = (select min(id) + 2 from app.audit_log)"
        )
        conn.execute("alter table app.audit_log enable trigger audit_no_update")
    assert not _valid(database, TENANT_A)


def test_tamper_by_removing_the_last_event_is_detected(database: Database, rls: Rls) -> None:
    _record(database, AuditLogger(CLOCK), TENANT_A, 3)
    with psycopg.connect(rls.admin_dsn, autocommit=True) as conn:
        conn.execute("alter table app.audit_log disable trigger audit_no_update")
        conn.execute("delete from app.audit_log where id = (select max(id) from app.audit_log)")
        conn.execute("alter table app.audit_log enable trigger audit_no_update")
    assert not _valid(database, TENANT_A)  # a cabeça guardada já não coincide


def test_concurrent_inserts_keep_chain_valid(database: Database) -> None:
    audit = AuditLogger(CLOCK)
    errors_seen: list[BaseException] = []

    def work() -> None:
        try:
            _record(database, audit, TENANT_A, 10)
        except BaseException as exc:
            errors_seen.append(exc)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert errors_seen == []
    assert _valid(database, TENANT_A)
    with database.tenant_tx(TENANT_A, USER_1) as cur:
        cur.execute("select count(*) as n from app.audit_log")
        assert cur.fetchone() == {"n": 40}


def test_inv03_metadata_with_long_text_rejected(database: Database) -> None:
    audit = AuditLogger(CLOCK)
    bad = (
        {"texto": "x"},  # chave fora da allowlist
        {"count": "y" * 201},  # texto longo
        {"count": ["lista"]},  # não escalar
        {"count": {"a": 1}},
    )
    for metadata in bad:
        with pytest.raises(ValidationFailed), database.tenant_tx(TENANT_A, USER_1) as cur:
            audit.record(cur, tenant_id=TENANT_A, actor_type="user", actor_id=None,
                         action="doc.read", metadata=metadata)  # fmt: skip
    with pytest.raises(ValidationFailed), database.tenant_tx(TENANT_A, USER_1) as cur:
        audit.record(cur, tenant_id=TENANT_A, actor_type="robot", actor_id=None, action="x")
    assert _valid(database, TENANT_A)


def test_a_tenant_cannot_write_audit_for_another_or_for_the_platform(database: Database) -> None:
    audit = AuditLogger(CLOCK)
    for target in (TENANT_B, None):
        with (
            pytest.raises(errors.InsufficientPrivilege),
            database.tenant_tx(TENANT_A, USER_1) as cur,
        ):
            audit.record(cur, tenant_id=target, actor_type="user", actor_id=None, action="doc.read")


def test_backoffice_writes_platform_events_only(rls: Rls) -> None:
    audit = AuditLogger(CLOCK)
    pool = make_pool(rls.dsn_for("app_backoffice"), max_size=2)
    pool.open(wait=True)
    try:
        with (
            pool.connection() as conn,
            conn.transaction(),
            conn.cursor(row_factory=psycopg.rows.dict_row) as cur,
        ):
            audit.record(
                cur, tenant_id=None, actor_type="staff", actor_id="s1", action="tenant.create"
            )
            audit.record(
                cur, tenant_id=None, actor_type="staff", actor_id="s1", action="tenant.suspend"
            )
            assert verify_chain(cur, "platform")
        with (
            pool.connection() as conn,
            conn.transaction(),
            conn.cursor(row_factory=psycopg.rows.dict_row) as cur,
            pytest.raises(errors.InsufficientPrivilege),
        ):
            audit.record(cur, tenant_id=TENANT_A, actor_type="staff", actor_id="s1", action="x")
    finally:
        pool.close()
