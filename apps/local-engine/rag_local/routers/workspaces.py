"""Pastas autorizadas e consentimento em lote (F11-T05; INV-10, INV-18)."""

from __future__ import annotations

import os
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from rag_core.errors import NotFound, ValidationFailed

from rag_local.classification import suggest_classification
from rag_local.consent import Action, State
from rag_local.state import LOCAL_TENANT, SUPPORTED_EXTENSIONS, LocalState

router = APIRouter(tags=["workspaces"])


def _state(request: Request) -> LocalState:
    state: LocalState | None = request.app.state.local
    if state is None:
        raise NotFound()
    return state


class CreateWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1024)
    allow_home: bool = False


class PatchWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_file_policy: Literal["ask", "auto_types", "never"]
    auto_types: list[str] = Field(default_factory=list, max_length=50)


class Approve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_ids: list[str] = Field(default_factory=list, max_length=5000)
    all_supported: bool = False
    except_ids: list[str] = Field(default_factory=list, alias="except", max_length=5000)


@router.post("/workspaces", status_code=201)
def create_workspace(body: CreateWorkspace, request: Request) -> dict[str, Any]:
    local = _state(request)
    root = local.gate.register_root(body.path, allow_home=body.allow_home)
    workspace = local.repo.add_workspace(root, os.path.basename(root) or root)
    proposed = 0
    for meta, reason in local.gate.scan(workspace):  # só metadados: nada é lido (nível 1)
        if reason is None and local.repo.propose(
            workspace, meta.rel_path, meta.size, meta.mtime, meta.ext
        ):
            proposed += 1
    return {"id": workspace, "display_name": os.path.basename(root), "files": proposed}


@router.get("/workspaces")
def list_workspaces(request: Request) -> list[dict[str, Any]]:
    return _state(request).repo.workspaces()


@router.get("/workspaces/{workspace_id}/files")
def list_files(
    workspace_id: str, request: Request, state: str | None = None
) -> list[dict[str, Any]]:
    local = _state(request)
    known = {d["rel_path"]: d for d in local.repo.documents(workspace_id)}
    items: list[dict[str, Any]] = []
    for meta, reason in local.gate.scan(workspace_id):
        doc = known.get(meta.rel_path)
        current = "excluded" if reason else (doc["state"] if doc else "new")
        if state is not None and current != state:
            continue
        items.append(
            {
                "doc_id": doc["doc_id"] if doc else None,
                "name": meta.name,
                "rel_path": meta.rel_path,
                "ext": meta.ext,
                "size": meta.size,
                "mtime": meta.mtime,
                "suggested_classification": suggest_classification(meta.rel_path),
                "state": current,
                "excluded_reason": reason,
            }
        )
    return items


@router.post("/workspaces/{workspace_id}/approve")
def approve(workspace_id: str, body: Approve, request: Request) -> dict[str, int]:
    local = _state(request)
    docs = {d["doc_id"]: d for d in local.repo.documents(workspace_id)}
    if body.all_supported:
        wanted = [
            doc_id
            for doc_id, d in docs.items()
            if os.path.splitext(d["rel_path"])[1].lower() in SUPPORTED_EXTENSIONS
        ]
    else:
        wanted = list(body.doc_ids)
    approved = skipped = 0
    for doc_id in wanted:
        if doc_id in body.except_ids:
            continue
        doc = docs.get(doc_id)
        if doc is None:
            raise ValidationFailed(subcode="unknown_document")
        if State(doc["state"]) not in (State.PENDING, State.REJECTED, State.REVOKED):
            skipped += 1  # já aprovado/indexado: nada a fazer
            continue
        local.repo.apply(doc_id, Action.APPROVE)
        local.repo.enqueue_job("index", doc_id, doc["rel_path"])
        approved += 1
    return {"approved": approved, "skipped": skipped}


@router.patch("/workspaces/{workspace_id}")
def patch_workspace(workspace_id: str, body: PatchWorkspace, request: Request) -> dict[str, str]:
    cleaned = [t.lower() for t in body.auto_types]
    if any(not t.startswith(".") or t not in SUPPORTED_EXTENSIONS for t in cleaned):
        raise ValidationFailed(subcode="invalid_auto_types")
    _state(request).repo.update_workspace(workspace_id, body.new_file_policy, cleaned)
    return {"status": "updated"}


@router.delete("/workspaces/{workspace_id}")
def delete_workspace(workspace_id: str, request: Request) -> dict[str, int]:
    """Apaga chunks e linhas; os ``consent_events`` ficam (registo de consentimento)."""
    local = _state(request)
    removed = 0
    for doc in local.repo.documents(workspace_id):
        removed += local.store.delete_document(LOCAL_TENANT, doc["doc_id"])
        local.repo.drop_jobs(doc["doc_id"])
    local.repo.remove_workspace(workspace_id)
    return {"chunks_removed": removed}
