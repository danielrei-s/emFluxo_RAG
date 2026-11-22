"""Auditoria com cadeia de hashes (F7-T06; INV-03, INV-16).

Cada evento guarda o hash do anterior do mesmo escopo (tenant ou ``platform``); alterar ou apagar
uma linha quebra a cadeia. As escritas passam por um cursor já com contexto (``tenant_tx``).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from psycopg import Cursor
from psycopg.rows import DictRow
from rag_core.errors import ValidationFailed
from rag_core.interfaces import Clock
from rag_core.logging import ALLOWED_KEYS

GENESIS = "0" * 64
PLATFORM = "platform"
MAX_VALUE_CHARS = 200
_ACTOR_TYPES = frozenset({"user", "staff", "device", "system"})


def validate_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Só chaves da allowlist de logs e valores escalares curtos (nunca conteúdo, INV-03)."""
    for key, value in metadata.items():
        if key not in ALLOWED_KEYS:
            raise ValidationFailed(subcode="audit_metadata_key")
        if value is not None and not isinstance(value, bool | int | float | str):
            raise ValidationFailed(subcode="audit_metadata_value")
        if isinstance(value, str) and len(value) > MAX_VALUE_CHARS:
            raise ValidationFailed(subcode="audit_metadata_too_long")
    return metadata


def compute_hash(prev_hash: str, fields: dict[str, Any]) -> str:
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(f"{prev_hash}|{payload}".encode()).hexdigest()


def _fields(
    tenant_id: str | None,
    actor_type: str,
    actor_id: str | None,
    action: str,
    resource_type: str | None,
    resource_id: str | None,
    metadata: dict[str, Any],
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "metadata": metadata,
        "created_at": created_at.astimezone(UTC).isoformat(),
    }


class AuditLogger:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def record(
        self,
        cur: Cursor[DictRow],
        *,
        tenant_id: str | None,
        actor_type: str,
        actor_id: str | None,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Acrescenta um evento à cadeia do escopo e devolve o seu hash."""
        if actor_type not in _ACTOR_TYPES:
            raise ValidationFailed(subcode="audit_actor_type")
        meta = validate_metadata(metadata or {})
        scope = tenant_id if tenant_id is not None else PLATFORM
        created_at = self._clock.now().astimezone(UTC)
        cur.execute(
            "insert into app.audit_heads (scope, last_hash) values (%s, %s) "
            "on conflict (scope) do nothing",
            (scope, GENESIS),
        )
        cur.execute("select last_hash from app.audit_heads where scope = %s for update", (scope,))
        head = cur.fetchone()
        prev = head["last_hash"] if head else GENESIS
        digest = compute_hash(
            prev,
            _fields(
                tenant_id,
                actor_type,
                actor_id,
                action,
                resource_type,
                resource_id,
                meta,
                created_at,
            ),
        )
        cur.execute(
            "insert into app.audit_log (tenant_id, actor_type, actor_id, action, resource_type, "
            "resource_id, metadata, created_at, prev_hash, hash) "
            "values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)",
            (
                tenant_id, actor_type, actor_id, action, resource_type, resource_id,
                json.dumps(meta), created_at, prev, digest,
            ),
        )  # fmt: skip
        cur.execute("update app.audit_heads set last_hash = %s where scope = %s", (digest, scope))
        return digest


def verify_chain(cur: Cursor[DictRow], scope: str) -> bool:
    """Reconstrói a cadeia do escopo e compara com as linhas e com a cabeça guardada."""
    if scope == PLATFORM:
        cur.execute("select * from app.audit_log where tenant_id is null order by id")
    else:
        cur.execute("select * from app.audit_log where tenant_id = %s order by id", (scope,))
    prev = GENESIS
    for row in cur.fetchall():
        fields = _fields(
            None if scope == PLATFORM else scope, row["actor_type"], row["actor_id"], row["action"],
            row["resource_type"], row["resource_id"], row["metadata"], row["created_at"],
        )  # fmt: skip
        if row["prev_hash"] != prev or row["hash"] != compute_hash(prev, fields):
            return False
        prev = row["hash"]
    cur.execute("select last_hash from app.audit_heads where scope = %s", (scope,))
    head = cur.fetchone()
    return (head["last_hash"] if head else GENESIS) == prev
