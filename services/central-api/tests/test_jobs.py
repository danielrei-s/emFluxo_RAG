"""Testes de F7-T07 (integração): fila de jobs, backoff, leases e worker (INV-03)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from conftest import TENANT_A, TENANT_B, USER_1, Rls
from rag_central import jobs
from rag_central.db import Database, make_pool
from rag_central.worker import JobContext, Worker
from rag_core.errors import UpstreamError, ValidationFailed

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
DOC = "11111111-0000-4000-8000-0000000000d1"


@pytest.fixture
def api(rls: Rls) -> Iterator[Database]:
    pool = make_pool(rls.dsn_for("app_api"), max_size=4)
    pool.open(wait=True)
    yield Database(pool)
    pool.close()


@pytest.fixture
def worker_db(rls: Rls) -> Iterator[Database]:
    pool = make_pool(rls.dsn_for("app_worker"), max_size=6)
    pool.open(wait=True)
    yield Database(pool, allow_system=True)
    pool.close()


def _enqueue(api: Database, tenant: str = TENANT_A, n: int = 1, **kwargs: Any) -> list[str | None]:
    ids: list[str | None] = []
    with api.tenant_tx(tenant, USER_1) as cur:
        for i in range(n):
            ids.append(jobs.enqueue(cur, tenant, "ingest", {"doc_id": f"d{i}"}, **kwargs))
    return ids


def _row(rls: Rls, job_id: str) -> dict[str, Any]:
    with psycopg.connect(rls.admin_dsn, row_factory=psycopg.rows.dict_row) as conn:
        row = conn.execute(
            "select *, now() as db_now from app.jobs where id = %s", (job_id,)
        ).fetchone()
    assert row is not None
    return row


def test_enqueue_claim_complete(api: Database, worker_db: Database, rls: Rls) -> None:
    (job_id,) = _enqueue(api)
    assert job_id is not None
    with worker_db.system_tx("job_claim") as cur:
        assert jobs.claim(cur, "w1", ["outro"]) is None  # tipo que o worker não trata
        job = jobs.claim(cur, "w1", ["ingest"])
        assert job is not None and job.id == job_id and job.tenant_id == TENANT_A
        assert (job.kind, job.payload, job.attempts) == ("ingest", {"doc_id": "d0"}, 1)
        assert jobs.claim(cur, "w2", ["ingest"]) is None  # já está reservado
    row = _row(rls, job_id)
    assert (row["status"], row["locked_by"]) == ("running", "w1")
    with worker_db.system_tx("job_claim") as cur:
        jobs.complete(cur, job_id)
    assert _row(rls, job_id)["status"] == "done"


def test_api_sees_only_its_tenant_jobs_and_worker_sees_all(
    api: Database, worker_db: Database
) -> None:
    _enqueue(api, TENANT_A, 2)
    _enqueue(api, TENANT_B, 3)
    with api.tenant_tx(TENANT_A, USER_1) as cur:
        cur.execute("select count(*) as n from app.jobs")
        assert cur.fetchone() == {"n": 2}
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # a API não altera jobs
            cur.execute("update app.jobs set status = 'done'")
    with worker_db.system_tx("job_claim") as cur:
        cur.execute("select count(*) as n from app.jobs")
        assert cur.fetchone() == {"n": 5}


def test_two_workers_never_claim_same_job(api: Database, worker_db: Database) -> None:
    _enqueue(api, TENANT_A, 20)
    _enqueue(api, TENANT_B, 20)
    claimed: dict[str, list[str]] = {"w1": [], "w2": [], "w3": []}
    errors: list[BaseException] = []

    def work(name: str) -> None:
        try:
            while True:
                with worker_db.system_tx("job_claim") as cur:
                    job = jobs.claim(cur, name, ["ingest"])
                if job is None:
                    return
                claimed[name].append(job.id)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(name,)) for name in claimed]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    everything = [job_id for ids in claimed.values() for job_id in ids]
    assert errors == []
    assert len(everything) == 40 and len(set(everything)) == 40  # nenhum repetido, nenhum perdido


def test_failure_backoff(api: Database, worker_db: Database, rls: Rls) -> None:
    (job_id,) = _enqueue(api)
    assert job_id is not None
    for expected_wait in (20, 40):  # 10 s * 2^attempts, com attempts = 1, 2
        with worker_db.system_tx("job_claim") as cur:
            cur.execute("update app.jobs set run_after = now() where id = %s", (job_id,))
            job = jobs.claim(cur, "w1", ["ingest"])
            assert job is not None
            assert jobs.fail(cur, job_id, "upstream_error") == "queued"
        row = _row(rls, job_id)
        wait = (row["run_after"] - row["db_now"]).total_seconds()
        assert expected_wait - 3 <= wait <= expected_wait + 1, wait
        assert row["last_error_code"] == "upstream_error" and row["locked_by"] is None
    with worker_db.system_tx("job_claim") as cur:  # ainda não está pronto: não é reservado
        assert jobs.claim(cur, "w1", ["ingest"]) is None


def test_dead_after_max_attempts(api: Database, worker_db: Database, rls: Rls) -> None:
    (job_id,) = _enqueue(api)
    assert job_id is not None
    with worker_db.system_tx("job_claim") as cur:
        cur.execute("update app.jobs set max_attempts = 2 where id = %s", (job_id,))
    for expected in ("queued", "dead"):
        with worker_db.system_tx("job_claim") as cur:
            cur.execute(
                "update app.jobs set run_after = now() where id = %s and status = 'queued'",
                (job_id,),
            )
            assert jobs.claim(cur, "w1", ["ingest"]) is not None
            assert jobs.fail(cur, job_id, "x") == expected
    assert _row(rls, job_id)["status"] == "dead"
    with worker_db.system_tx("job_claim") as cur:
        assert jobs.claim(cur, "w1", ["ingest"]) is None
        assert jobs.fail(cur, "00000000-0000-4000-8000-0000000000ff", "x") == "missing"


def test_expired_lease_requeued(api: Database, worker_db: Database, rls: Rls) -> None:
    (job_id,) = _enqueue(api)
    assert job_id is not None
    with worker_db.system_tx("job_claim") as cur:
        assert jobs.claim(cur, "w1", ["ingest"]) is not None  # w1 "morre" sem terminar
    with worker_db.system_tx("job_claim") as cur:
        assert jobs.claim(cur, "w2", ["ingest"]) is None  # o lease ainda é válido
        cur.execute(
            "update app.jobs set locked_at = now() - interval '10 minutes' where id = %s", (job_id,)
        )
        job = jobs.claim(cur, "w2", ["ingest"])
        assert job is not None and job.id == job_id and job.attempts == 2
    row = _row(rls, job_id)
    assert (row["locked_by"], row["last_error_code"]) == ("w2", "lease_expired")
    with worker_db.system_tx("job_claim") as cur:  # no limite de tentativas passa a dead
        cur.execute(
            "update app.jobs set max_attempts = 2, locked_at = now() - interval '10 minutes' where id = %s",
            (job_id,),
        )
        assert jobs.recover_expired(cur) == 1
    assert _row(rls, job_id)["status"] == "dead"


def test_inv03_payload_rejects_content_keys(api: Database) -> None:
    for payload in (
        {"texto": "olá"},  # chave de conteúdo
        {"doc_id": "x" * 201},  # demasiado longo
        {"doc_id": ["a"]},  # não escalar
    ):
        with pytest.raises(ValidationFailed), api.tenant_tx(TENANT_A, USER_1) as cur:
            jobs.enqueue(cur, TENANT_A, "ingest", payload)
    with api.tenant_tx(TENANT_A, USER_1) as cur:
        assert jobs.enqueue(cur, TENANT_A, "ingest", {"doc_id": DOC, "count": 3, "stage": "parse"})


def test_dedupe_key(api: Database) -> None:
    first = _enqueue(api, dedupe_key="doc-1")
    again = _enqueue(api, dedupe_key="doc-1")
    other_kind = None
    with api.tenant_tx(TENANT_A, USER_1) as cur:
        other_kind = jobs.enqueue(cur, TENANT_A, "delete", {"doc_id": "d"}, dedupe_key="doc-1")
    assert first[0] is not None and again == [None] and other_kind is not None


def test_worker_runs_handlers_in_tenant_context_and_records_error_codes_only(
    api: Database, worker_db: Database, rls: Rls
) -> None:
    ok_id, boom_id, plain_id = (_enqueue(api, n=1)[0] for _ in range(3))
    with worker_db.system_tx("job_claim") as cur:  # distingue-os pelo payload
        cur.execute("update app.jobs set kind = 'boom' where id = %s", (boom_id,))
        cur.execute("update app.jobs set kind = 'plain' where id = %s", (plain_id,))
    seen: list[tuple[str, str]] = []

    def ok(job: jobs.Job, ctx: JobContext) -> None:
        with ctx.tx() as cur:
            cur.execute("select count(*) as n, app.current_tenant()::text as t from app.workspaces")
            row = cur.fetchone()
        assert row is not None
        seen.append((job.id, f"{row['n']}:{row['t']}"))

    def boom(job: jobs.Job, ctx: JobContext) -> None:
        raise UpstreamError("segredo-no-texto: CANARIO")

    def plain(job: jobs.Job, ctx: JobContext) -> None:
        raise RuntimeError("CANARIO outra vez")

    worker = Worker(worker_db, {"ingest": ok, "boom": boom, "plain": plain}, "w1")
    assert len(list(worker.drain())) == 3 and worker.run_once() is False
    assert seen == [(ok_id, f"1:{TENANT_A}")]
    assert _row(rls, ok_id or "")["status"] == "done"
    for job_id, code in ((boom_id, "upstream_error"), (plain_id, "handler_error")):
        row = _row(rls, job_id or "")
        assert (row["status"], row["last_error_code"]) == (
            "queued",
            code,
        )  # volta à fila com backoff
        assert "CANARIO" not in str(row)
