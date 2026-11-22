"""Fila de jobs em Postgres (F7-T07). Os payloads só levam IDs e metadados, nunca conteúdo."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg import Cursor
from psycopg.rows import DictRow
from rag_core.errors import ValidationFailed
from rag_core.logging import ALLOWED_KEYS

LEASE_S = 300
BACKOFF_BASE_S = 10
MAX_VALUE_CHARS = 200
_ERROR_CODE = re.compile(r"[a-z0-9_]{1,64}")


@dataclass(frozen=True)
class Job:
    id: str
    tenant_id: str
    kind: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


def validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Chaves terminadas em ``_id`` ou da allowlist de logs; valores escalares curtos."""
    for key, value in payload.items():
        if not (key.endswith("_id") or key in ALLOWED_KEYS):
            raise ValidationFailed(subcode="job_payload_key")
        if value is not None and not isinstance(value, bool | int | float | str):
            raise ValidationFailed(subcode="job_payload_value")
        if isinstance(value, str) and len(value) > MAX_VALUE_CHARS:
            raise ValidationFailed(subcode="job_payload_too_long")
    return payload


def enqueue(
    cur: Cursor[DictRow],
    tenant_id: str,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    run_after: datetime | None = None,
    dedupe_key: str | None = None,
) -> str | None:
    """Cria o job e devolve o id; com ``dedupe_key`` repetida não cria nada e devolve ``None``."""
    body = validate_payload(payload or {})
    cur.execute(
        "insert into app.jobs (tenant_id, kind, payload, run_after, dedupe_key) "
        "values (%s, %s, %s::jsonb, coalesce(%s, now()), %s) "
        "on conflict (kind, dedupe_key) do nothing returning id::text as id",
        (tenant_id, kind, json.dumps(body), run_after, dedupe_key),
    )
    row = cur.fetchone()
    return row["id"] if row else None


def recover_expired(cur: Cursor[DictRow], lease_s: int = LEASE_S) -> int:
    """Devolve à fila (ou marca ``dead``) os jobs ``running`` cujo lease expirou."""
    cur.execute(
        "update app.jobs set status = case when attempts >= max_attempts then 'dead' "
        "else 'queued' end, locked_by = null, locked_at = null, updated_at = now(), "
        "last_error_code = 'lease_expired' "
        "where status = 'running' and locked_at < now() - make_interval(secs => %s)",
        (lease_s,),
    )
    return cur.rowcount


def claim(
    cur: Cursor[DictRow], worker_id: str, kinds: list[str], lease_s: int = LEASE_S
) -> Job | None:
    """Reserva um job pronto (``FOR UPDATE SKIP LOCKED``): dois workers nunca ficam com o mesmo."""
    recover_expired(cur, lease_s)
    cur.execute(
        "update app.jobs set status = 'running', locked_by = %s, locked_at = now(), "
        "attempts = attempts + 1, updated_at = now() "
        "where id = (select id from app.jobs where status = 'queued' and run_after <= now() "
        "and kind = any(%s) order by run_after for update skip locked limit 1) "
        "returning id::text as id, tenant_id::text as tenant_id, kind, payload, attempts, "
        "max_attempts",
        (worker_id, kinds),
    )
    row = cur.fetchone()
    return Job(**row) if row else None


def complete(cur: Cursor[DictRow], job_id: str) -> None:
    cur.execute(
        "update app.jobs set status = 'done', locked_by = null, locked_at = null, "
        "updated_at = now() where id = %s",
        (job_id,),
    )


def fail(cur: Cursor[DictRow], job_id: str, error_code: str) -> str:
    """Repõe na fila com backoff ``10 s * 2^attempts`` ou marca ``dead``; devolve o estado."""
    if not _ERROR_CODE.fullmatch(error_code):
        error_code = "handler_error"  # nunca texto livre (INV-03)
    cur.execute(
        "update app.jobs set status = case when attempts >= max_attempts then 'dead' "
        "else 'queued' end, run_after = now() + make_interval(secs => %s * power(2, attempts)), "
        "last_error_code = %s, locked_by = null, locked_at = null, updated_at = now() "
        "where id = %s returning status",
        (BACKOFF_BASE_S, error_code, job_id),
    )
    row = cur.fetchone()
    return str(row["status"]) if row else "missing"
