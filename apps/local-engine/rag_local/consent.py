"""Máquina de estados do consentimento por documento (F11-T03; INV-10).

Nada é indexado sem aprovação explícita; revogar apaga o acesso. Cada transição fica registada
em ``consent_events`` (sem conteúdo: só identificadores, ação e quem a fez).
"""

from __future__ import annotations

from enum import StrEnum

from rag_core.errors import ConsentError


class State(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    INDEXED = "indexed"
    FAILED = "failed"
    REVOKED = "revoked"


class Action(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    INDEX_OK = "index_ok"
    INDEX_FAIL = "index_fail"
    REVOKE = "revoke"
    FILE_CHANGED = "file_changed"


TRANSITIONS: dict[tuple[State, Action], State] = {
    (State.PENDING, Action.APPROVE): State.APPROVED,
    (State.PENDING, Action.REJECT): State.REJECTED,
    (State.APPROVED, Action.INDEX_OK): State.INDEXED,
    (State.APPROVED, Action.INDEX_FAIL): State.FAILED,
    (State.INDEXED, Action.REVOKE): State.REVOKED,
    (State.APPROVED, Action.REVOKE): State.REVOKED,
    (State.FAILED, Action.REVOKE): State.REVOKED,
    (State.REVOKED, Action.APPROVE): State.APPROVED,
    (State.REJECTED, Action.APPROVE): State.APPROVED,
    (State.INDEXED, Action.FILE_CHANGED): State.APPROVED,
}


def transition(state: State, action: Action) -> State:
    """Novo estado, ou ``ConsentError`` para qualquer combinação não prevista."""
    try:
        return TRANSITIONS[(state, action)]
    except KeyError:
        raise ConsentError("invalid_transition") from None
