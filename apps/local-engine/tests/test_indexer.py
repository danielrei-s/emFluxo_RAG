"""Testes de F11-T06: indexador (política de novos ficheiros, alterações, eliminações, fila)."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from rag_core.config import Settings
from rag_core.fakes import FakeEmbedder
from rag_core.ingestion.pipeline import IngestionService
from rag_core.stores import SqliteVectorStore
from rag_local.consent import State
from rag_local.events import EventBus
from rag_local.filegate import FileGate
from rag_local.indexer import Indexer
from rag_local.repo import LocalRepo
from rag_local.state import LOCAL_TENANT

DIM = FakeEmbedder().dim


class Rig:
    def __init__(self, db: Path | None = None) -> None:
        conn = sqlite3.connect(str(db) if db else ":memory:", check_same_thread=False)
        self.repo = LocalRepo(conn)
        self.gate = FileGate(self.repo)
        store_conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.store = SqliteVectorStore(lambda: store_conn, DIM)
        self.events = EventBus()
        ingestion = IngestionService(
            embedder=FakeEmbedder(), store=self.store, settings=Settings.for_tests()
        )
        self.indexer = Indexer(self.repo, self.gate, self.store, ingestion, self.events)

    def workspace(self, root: Path, policy: str = "ask", types: list[str] | None = None) -> str:
        return self.repo.add_workspace(self.gate.register_root(str(root)), "T", policy, types)  # type: ignore[arg-type]

    def chunks(self) -> int:
        return len(self.store.document_hashes(LOCAL_TENANT, next(iter(self._ws()))))

    def _ws(self) -> list[str]:
        return [w["id"] for w in self.repo.workspaces()]

    def states(self, workspace: str) -> dict[str, str]:
        return {d["rel_path"]: d["state"] for d in self.repo.documents(workspace)}


def _write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_policy_ask_auto_never(tmp_path: Path) -> None:
    rig = Rig()
    for name, policy, types in (("ask", "ask", None), ("auto", "auto_types", [".txt"]),
                                ("never", "never", None)):  # fmt: skip
        root = tmp_path / name
        _write(root, "a.txt", f"texto {name}")
        _write(root, "b.pdf", "x")
        _write(root, ".env", "SEGREDO=1")
        workspace = rig.workspace(root, policy, types)
        counts = rig.indexer.rescan(workspace)
        states = rig.states(workspace)
        if name == "ask":
            assert states == {"a.txt": "pending", "b.pdf": "pending"} and counts["pending"] == 2
            assert rig.repo.jobs() == []
        elif name == "auto":
            assert states == {"a.txt": "approved", "b.pdf": "pending"} and counts["queued"] == 1
            assert [j["rel_path"] for j in rig.repo.jobs()] == ["a.txt"]
        else:
            assert states == {"a.txt": "rejected", "b.pdf": "rejected"}
            assert counts["rejected"] == 2
    assert {e["actor"] for e in rig.repo.events() if e["action"] == "approve"} == {"policy"}
    published = rig.events.drain()
    assert all(
        set(e) <= {"type", "pending", "queued", "rejected", "changed", "deleted"} for e in published
    )


def test_auto_types_indexes_and_modified_file_reindexed_only(tmp_path: Path) -> None:
    rig = Rig()
    root = tmp_path / "docs"
    _write(root, "a.txt", "Primeiro documento sobre férias.")
    path_b = _write(root, "b.txt", "Segundo documento sobre orçamento.")
    workspace = rig.workspace(root, "auto_types", [".txt"])
    rig.indexer.rescan(workspace)
    assert rig.indexer.drain() == 2
    assert rig.states(workspace) == {"a.txt": "indexed", "b.txt": "indexed"}
    assert len(rig.store.document_hashes(LOCAL_TENANT, workspace)) == 2
    assert rig.indexer.rescan(workspace)["changed"] == 0 and rig.repo.jobs() == []  # nada mudou
    path_b.write_text("Segundo documento revisto, bastante maior do que antes.", encoding="utf-8")
    counts = rig.indexer.rescan(workspace)
    assert counts["changed"] == 1
    assert [j["rel_path"] for j in rig.repo.jobs()] == ["b.txt"]  # só o alterado
    assert rig.states(workspace)["b.txt"] == "approved"  # voltou à fila
    rig.indexer.rescan(workspace)
    assert len(rig.repo.jobs()) == 1  # sem duplicar trabalhos
    rig.indexer.drain()
    assert rig.states(workspace) == {"a.txt": "indexed", "b.txt": "indexed"}
    assert rig.repo.document(
        next(d["doc_id"] for d in rig.repo.documents(workspace) if d["rel_path"] == "b.txt")
    )["file_hash"]


def test_inv18_deleted_file_removed(tmp_path: Path) -> None:
    rig = Rig()
    root = tmp_path / "docs"
    gone = _write(root, "a.txt", "Documento que vai desaparecer do disco.")
    _write(root, "b.txt", "Documento que fica.")
    workspace = rig.workspace(root, "auto_types", [".txt"])
    rig.indexer.rescan(workspace)
    rig.indexer.drain()
    assert len(rig.store.document_hashes(LOCAL_TENANT, workspace)) == 2
    os.remove(gone)
    assert rig.indexer.rescan(workspace)["deleted"] == 1
    rig.indexer.drain()
    assert list(rig.states(workspace)) == ["b.txt"]
    assert len(rig.store.document_hashes(LOCAL_TENANT, workspace)) == 1  # chunks removidos


def test_revoked_or_unsupported_documents_do_not_break_the_queue(tmp_path: Path) -> None:
    rig = Rig()
    root = tmp_path / "docs"
    _write(root, "vazio.txt", "")
    _write(root, "ok.txt", "Texto normal para indexar.")
    workspace = rig.workspace(root, "auto_types", [".txt"])
    rig.indexer.rescan(workspace)
    rig.indexer.drain()
    states = rig.states(workspace)
    assert states["ok.txt"] == "indexed" and states["vazio.txt"] == "failed"  # sem texto extraído
    failed = next(d for d in rig.repo.documents(workspace) if d["rel_path"] == "vazio.txt")
    assert failed["state"] == State.FAILED
    assert "failed" in {e["type"] for e in rig.events.drain()}


def test_queue_survives_restart(tmp_path: Path) -> None:
    db = tmp_path / "local.db"
    root = tmp_path / "docs"
    _write(root, "a.txt", "Documento que será indexado depois do reinício.")
    first = Rig(db)
    workspace = first.workspace(root, "auto_types", [".txt"])
    first.indexer.rescan(workspace)
    assert len(first.repo.jobs()) == 1
    del first  # "o motor fecha"
    second = Rig(db)
    assert [j["rel_path"] for j in second.repo.jobs()] == ["a.txt"]
    assert second.indexer.drain() == 1
    assert second.states(workspace) == {"a.txt": "indexed"} and second.repo.jobs() == []


def test_revoke_between_enqueue_and_run_skips_indexing(tmp_path: Path) -> None:
    from rag_local.consent import Action

    rig = Rig()
    root = tmp_path / "docs"
    _write(root, "a.txt", "Texto.")
    workspace = rig.workspace(root, "auto_types", [".txt"])
    rig.indexer.rescan(workspace)
    doc = rig.repo.documents(workspace)[0]["doc_id"]
    rig.repo.apply(doc, Action.REVOKE)
    rig.indexer.drain()
    assert rig.states(workspace) == {"a.txt": "revoked"}
    assert rig.store.document_hashes(LOCAL_TENANT, workspace) == {}
    assert pytest is not None
