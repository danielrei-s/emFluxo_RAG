"""Decisões sobre documentos: rejeitar, revogar (apaga já os chunks) e propriedades (F11-T05)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from rag_core.errors import NotFound, ValidationFailed

from rag_local.consent import Action
from rag_local.state import LOCAL_TENANT, LocalState

router = APIRouter(tags=["documents"])


def _state(request: Request) -> LocalState:
    state: LocalState | None = request.app.state.local
    if state is None:
        raise NotFound()
    return state


class PatchDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_only: bool | None = None
    classification: str | None = None


@router.post("/documents/{doc_id}/reject")
def reject(doc_id: str, request: Request) -> dict[str, str]:
    local = _state(request)
    new_state = local.repo.apply(doc_id, Action.REJECT)
    local.repo.drop_jobs(doc_id)
    return {"state": str(new_state)}


@router.post("/documents/{doc_id}/revoke")
def revoke(doc_id: str, request: Request) -> dict[str, object]:
    """Revoga e apaga os chunks de imediato e de forma síncrona (INV-18)."""
    local = _state(request)
    new_state = local.repo.apply(doc_id, Action.REVOKE)
    local.repo.drop_jobs(doc_id)
    removed = local.store.delete_document(LOCAL_TENANT, doc_id)
    return {"state": str(new_state), "chunks_removed": removed}


@router.patch("/documents/{doc_id}")
def patch_document(doc_id: str, body: PatchDocument, request: Request) -> dict[str, object]:
    local = _state(request)
    if body.local_only is None and body.classification is None:
        raise ValidationFailed(subcode="nothing_to_update")
    local.repo.state(doc_id)  # 404 se não existir
    if body.classification is not None:
        local.repo.set_classification(doc_id, body.classification)
    if body.local_only is not None:
        local.repo.set_local_only(doc_id, body.local_only)
    return {"status": "updated"}
