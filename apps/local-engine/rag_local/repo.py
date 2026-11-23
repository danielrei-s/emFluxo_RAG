"""Tabelas locais: pastas autorizadas, estado dos documentos e consentimento (F11-T03)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from rag_core.errors import NotFound, ValidationFailed

from rag_local.classification import suggest_classification
from rag_local.consent import Action, State, transition
from rag_local.exclusions import exclusion_reason

NewFilePolicy = Literal["ask", "auto_types", "never"]
SCHEMA = """
create table if not exists workspaces (
  id text primary key, root_path text not null unique, display_name text not null,
  new_file_policy text not null default 'ask'
    check (new_file_policy in ('ask','auto_types','never')),
  auto_types text not null default '[]', created_at text not null);
create table if not exists local_documents (
  doc_id text primary key, workspace_id text not null references workspaces(id) on delete cascade,
  rel_path text not null, size integer not null, mtime real not null, file_hash text,
  ext text not null, suggested_classification text not null, classification text not null,
  state text not null, local_only integer not null default 1, error_code text,
  updated_at text not null, unique (workspace_id, rel_path));
create table if not exists consent_events (
  id integer primary key autoincrement, ts text not null, workspace_id text not null,
  doc_id text, action text not null, actor text not null);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class LocalRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        conn.execute("pragma foreign_keys = on")  # o SQLite não aplica o cascade sem isto
        conn.executescript(SCHEMA)
        conn.commit()

    # -------------------------------------------------------------- pastas
    def add_workspace(
        self,
        root_path: str,
        display_name: str,
        policy: NewFilePolicy = "ask",
        auto_types: list[str] | None = None,
    ) -> str:
        workspace_id = uuid.uuid4().hex
        try:
            self._conn.execute(
                "insert into workspaces (id, root_path, display_name, new_file_policy, auto_types, "
                "created_at) values (?, ?, ?, ?, ?, ?)",
                (
                    workspace_id,
                    root_path,
                    display_name,
                    policy,
                    json.dumps(auto_types or []),
                    _now(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValidationFailed(subcode="workspace_exists") from exc
        self._event(workspace_id, None, "workspace_add", "user")
        self._conn.commit()
        return workspace_id

    def workspaces(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "select id, root_path, display_name, new_file_policy, auto_types from workspaces "
            "order by display_name"
        ).fetchall()
        return [
            {"id": r[0], "root_path": r[1], "display_name": r[2], "new_file_policy": r[3],
             "auto_types": json.loads(r[4])}
            for r in rows
        ]  # fmt: skip

    def remove_workspace(self, workspace_id: str) -> None:
        self._event(workspace_id, None, "workspace_remove", "user")
        self._conn.execute("delete from workspaces where id = ?", (workspace_id,))
        self._conn.commit()

    # ---------------------------------------------------------- documentos
    def propose(
        self, workspace_id: str, rel_path: str, size: int, mtime: float, ext: str
    ) -> str | None:
        """Regista um ficheiro como ``pending``; devolve ``None`` se estiver excluído."""
        if exclusion_reason(rel_path) is not None:
            return None
        doc_id = uuid.uuid4().hex
        suggested = suggest_classification(rel_path)
        try:
            self._conn.execute(
                "insert into local_documents (doc_id, workspace_id, rel_path, size, mtime, ext, "
                "suggested_classification, classification, state, updated_at) "
                "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (doc_id, workspace_id, rel_path, size, mtime, ext.lower(), suggested, suggested,
                 State.PENDING, _now()),
            )  # fmt: skip
        except sqlite3.IntegrityError as exc:
            raise ValidationFailed(subcode="document_exists") from exc
        self._conn.commit()
        return doc_id

    def state(self, doc_id: str) -> State:
        row = self._conn.execute(
            "select state from local_documents where doc_id = ?", (doc_id,)
        ).fetchone()
        if row is None:
            raise NotFound()
        return State(row[0])

    def apply(self, doc_id: str, action: Action, actor: str = "user") -> State:
        """Aplica uma transição e grava o evento de consentimento (INV-10)."""
        row = self._conn.execute(
            "select workspace_id, state from local_documents where doc_id = ?", (doc_id,)
        ).fetchone()
        if row is None:
            raise NotFound()
        new_state = transition(State(row[1]), action)  # ConsentError se não for permitido
        self._conn.execute(
            "update local_documents set state = ?, updated_at = ? where doc_id = ?",
            (new_state, _now(), doc_id),
        )
        self._event(row[0], doc_id, str(action), actor)
        self._conn.commit()
        return new_state

    def set_classification(self, doc_id: str, classification: str) -> None:
        if classification not in {"public", "internal", "confidential", "restricted"}:
            raise ValidationFailed(subcode="invalid_classification")
        self._conn.execute(
            "update local_documents set classification = ?, updated_at = ? where doc_id = ?",
            (classification, _now(), doc_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------- eventos
    def _event(self, workspace_id: str, doc_id: str | None, action: str, actor: str) -> None:
        self._conn.execute(
            "insert into consent_events (ts, workspace_id, doc_id, action, actor) "
            "values (?, ?, ?, ?, ?)",
            (_now(), workspace_id, doc_id, action, actor),
        )

    def events(self, doc_id: str | None = None) -> list[dict[str, Any]]:
        if doc_id is None:
            rows = self._conn.execute(
                "select ts, workspace_id, doc_id, action, actor from consent_events order by id"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "select ts, workspace_id, doc_id, action, actor from consent_events "
                "where doc_id = ? order by id",
                (doc_id,),
            ).fetchall()
        return [
            {"ts": r[0], "workspace_id": r[1], "doc_id": r[2], "action": r[3], "actor": r[4]}
            for r in rows
        ]
