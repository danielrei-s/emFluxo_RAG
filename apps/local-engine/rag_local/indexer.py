"""Mantém o índice local atualizado: novos ficheiros, alterações e eliminações (F11-T06; INV-18).

A política de novos ficheiros decide o que acontece sem perguntar (``ask`` / ``auto_types`` /
``never``). Os bytes chegam sempre pelo FileGate e a ingestão corre no sandbox (perfil lite).
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

from rag_core.errors import RagError
from rag_core.ingestion.pipeline import IngestionService
from rag_core.interfaces import VectorStore
from rag_core.types import Acl, Classification, Origin, SourceFile

from rag_local.consent import Action, State
from rag_local.events import EventBus
from rag_local.filegate import FileGate
from rag_local.repo import LocalRepo
from rag_local.state import LOCAL_TENANT

MAX_FILE_BYTES = 50 * 1024 * 1024


class Indexer:
    def __init__(
        self,
        repo: LocalRepo,
        gate: FileGate,
        store: VectorStore,
        ingestion: IngestionService,
        events: EventBus | None = None,
    ) -> None:
        self._repo = repo
        self._gate = gate
        self._store = store
        self._ingestion = ingestion
        self._events = events or EventBus()

    # ------------------------------------------------------------- reanálise
    def rescan(self, workspace_id: str) -> dict[str, int]:
        """Compara a pasta com o registo; aplica a política aos novos e enfileira o resto."""
        workspace = next(w for w in self._repo.workspaces() if w["id"] == workspace_id)
        policy, auto_types = workspace["new_file_policy"], set(workspace["auto_types"])
        on_disk = {m.rel_path: m for m, reason in self._gate.scan(workspace_id) if reason is None}
        known = {d["rel_path"]: d for d in self._repo.documents(workspace_id)}
        counts = {"pending": 0, "queued": 0, "rejected": 0, "changed": 0, "deleted": 0}
        for rel, meta in on_disk.items():
            doc = known.get(rel)
            if doc is None:
                doc_id = self._repo.propose(workspace_id, rel, meta.size, meta.mtime, meta.ext)
                if doc_id is None:
                    continue
                if policy == "auto_types" and meta.ext in auto_types:
                    self._repo.apply(doc_id, Action.APPROVE, actor="policy")
                    self._repo.enqueue_job("index", doc_id, rel)
                    counts["queued"] += 1
                elif policy == "never":
                    self._repo.apply(doc_id, Action.REJECT, actor="policy")
                    counts["rejected"] += 1
                else:  # ask (e auto_types fora da lista): espera pela decisão do utilizador
                    counts["pending"] += 1
                continue
            full = self._repo.document(doc["doc_id"])
            changed = full["size"] != meta.size or abs(full["mtime"] - meta.mtime) > 1e-6
            if changed and State(full["state"]) in (State.INDEXED, State.APPROVED, State.FAILED):
                if State(full["state"]) is State.INDEXED:
                    self._repo.apply(doc["doc_id"], Action.FILE_CHANGED, actor="engine")
                self._enqueue_once("index", doc["doc_id"], rel)
                counts["changed"] += 1
        for rel, doc in known.items():
            if rel not in on_disk:
                self._enqueue_once("delete", doc["doc_id"], rel)
                counts["deleted"] += 1
        self._events.publish("rescan", **counts)  # só contagens (a UI não recebe nomes)
        return counts

    def _enqueue_once(self, kind: str, doc_id: str, rel_path: str) -> None:
        if not self._repo.has_job(kind, doc_id):
            self._repo.enqueue_job(kind, doc_id, rel_path)

    # ------------------------------------------------------------- trabalhos
    def run_next(self) -> bool:
        job = self._repo.next_job()
        if job is None:
            return False
        try:
            if job["kind"] == "delete":
                self._delete(job["doc_id"])
            elif job["kind"] == "index":
                self._index(job["doc_id"])
        finally:
            self._repo.finish_job(job["id"])
        return True

    def drain(self, limit: int = 10_000) -> int:
        done = 0
        while done < limit and self.run_next():
            done += 1
        return done

    def _delete(self, doc_id: str) -> None:
        self._ingestion.delete(LOCAL_TENANT, doc_id)  # chunks do documento e dos anexos (INV-18)
        self._repo.delete_document_row(doc_id)
        self._events.publish("deleted", count=1)

    def _index(self, doc_id: str) -> None:
        doc: dict[str, Any] = self._repo.document(doc_id)
        if State(doc["state"]) is not State.APPROVED:
            return  # revogado ou rejeitado entretanto
        try:
            data, _ = self._gate.read_bytes(doc_id, MAX_FILE_BYTES)
            path = self._gate.resolve(doc["workspace_id"], doc["rel_path"])
            source = SourceFile(
                tenant_id=LOCAL_TENANT,
                workspace_id=doc["workspace_id"],
                doc_id=doc_id,
                source_uri=f"file://{doc['rel_path']}",
                filename=os.path.basename(doc["rel_path"]),
                acl=Acl(all_members=True),
                classification=Classification(doc["classification"]),
                origin=Origin.LOCAL,
                local_only=doc["local_only"],
            )
            result = self._ingestion.ingest_file(source, data)[0]
        except RagError as exc:
            self._fail(doc_id, exc.code)
            return
        if result.status == "failed":
            self._fail(doc_id, result.error_code or "ingestion_failed")
            return
        info = path.stat()
        self._repo.update_file_info(
            doc_id, len(data), info.st_mtime, hashlib.sha256(data).hexdigest()
        )
        self._repo.apply(doc_id, Action.INDEX_OK, actor="engine")
        self._events.publish("indexed", count=1)

    def _fail(self, doc_id: str, code: str) -> None:
        self._repo.apply(doc_id, Action.INDEX_FAIL, actor="engine")
        self._repo.set_error(doc_id, code)
        self._events.publish("failed", count=1)


__all__ = ["Indexer", "VectorStore"]
