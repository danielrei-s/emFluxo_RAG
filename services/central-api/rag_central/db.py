"""Acesso à BD central (F7-T03): todo o SQL passa por ``tenant_tx`` ou ``system_tx`` (INV-01).

O contexto de tenant vive só na transação (``set_config(..., true)``), por isso nunca vaza para o
pedido seguinte que reutilize a ligação do pool.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg import Cursor
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool
from rag_core.errors import AccessDenied, ValidationFailed
from rag_core.logging import get_logger

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
SYSTEM_REASONS = frozenset({"job_claim", "migration", "maintenance"})


def make_pool(dsn: str, *, min_size: int = 1, max_size: int = 10) -> ConnectionPool[Any]:
    """Pool compatível com o pooler em modo transação (sem prepared statements)."""
    return ConnectionPool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        kwargs={"prepare_threshold": None, "row_factory": dict_row},
        open=False,
    )


class Database:
    """``allow_system`` só é ligado para o worker; a Central API nunca o liga."""

    def __init__(self, pool: ConnectionPool[Any], *, allow_system: bool = False) -> None:
        self._pool = pool
        self._allow_system = allow_system

    @contextmanager
    def tenant_tx(self, tenant_id: str, user_id: str | None = None) -> Iterator[Cursor[DictRow]]:
        """Transação com ``app.tenant_id`` e ``app.user_id``; revertida em caso de erro."""
        if not _UUID.fullmatch(tenant_id) or (user_id is not None and not _UUID.fullmatch(user_id)):
            raise ValidationFailed(subcode="invalid_tenant_context")
        with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                "select set_config('app.tenant_id', %s, true), set_config('app.user_id', %s, true)",
                (tenant_id, user_id or ""),
            )
            yield cur

    @contextmanager
    def user_tx(self, user_id: str) -> Iterator[Cursor[DictRow]]:
        """Só ``app.user_id``: o utilizador vê as suas pertenças antes de escolher o tenant."""
        if not _UUID.fullmatch(user_id):
            raise ValidationFailed(subcode="invalid_tenant_context")
        with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("select set_config('app.user_id', %s, true)", (user_id,))
            yield cur

    @contextmanager
    def system_tx(self, reason: str) -> Iterator[Cursor[DictRow]]:
        """Sem contexto de tenant: só para claim de jobs, migrações e manutenção."""
        if not self._allow_system:
            raise AccessDenied("system_tx_not_allowed")
        if reason not in SYSTEM_REASONS:
            raise ValidationFailed(subcode="unknown_system_reason")
        get_logger("db").info("system_tx", reason=reason)
        with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            yield cur
