"""Testes de F11-T03: consentimento por documento e eventos (INV-10)."""

from __future__ import annotations

import itertools
import sqlite3

import pytest
from rag_core.errors import ConsentError, NotFound, ValidationFailed
from rag_local.consent import TRANSITIONS, Action, State, transition
from rag_local.repo import LocalRepo


@pytest.fixture
def repo() -> LocalRepo:
    return LocalRepo(sqlite3.connect(":memory:"))


def test_transition_table_exhaustive() -> None:
    allowed = 0
    for state, action in itertools.product(State, Action):
        if (state, action) in TRANSITIONS:
            assert transition(state, action) is TRANSITIONS[(state, action)]
            allowed += 1
        else:
            with pytest.raises(ConsentError):
                transition(state, action)
    assert allowed == 10 and len(State) * len(Action) == 36
    assert transition(State.PENDING, Action.APPROVE) is State.APPROVED
    assert transition(State.INDEXED, Action.FILE_CHANGED) is State.APPROVED
    assert transition(State.REVOKED, Action.APPROVE) is State.APPROVED
    for forbidden in (State.PENDING, State.REJECTED, State.REVOKED):  # nada é indexado sem aprovar
        with pytest.raises(ConsentError):
            transition(forbidden, Action.INDEX_OK)


def test_consent_events_recorded(repo: LocalRepo) -> None:
    workspace = repo.add_workspace("C:/Docs", "Documentos")
    doc = repo.propose(workspace, "RH/contrato.pdf", 10, 1.0, ".PDF")
    assert doc is not None and repo.state(doc) is State.PENDING
    assert repo.apply(doc, Action.APPROVE) is State.APPROVED
    assert repo.apply(doc, Action.INDEX_OK, actor="engine") is State.INDEXED
    assert repo.apply(doc, Action.REVOKE) is State.REVOKED
    with pytest.raises(ConsentError):  # um revogado não volta a indexar sem nova aprovação
        repo.apply(doc, Action.INDEX_OK)
    assert repo.state(doc) is State.REVOKED
    events = repo.events(doc)
    assert [(e["action"], e["actor"]) for e in events] == [
        ("approve", "user"), ("index_ok", "engine"), ("revoke", "user"),
    ]  # fmt: skip
    assert all(set(e) == {"ts", "workspace_id", "doc_id", "action", "actor"} for e in events)
    assert next(e["action"] for e in repo.events()) == "workspace_add"  # sem conteúdo nem caminhos
    assert "contrato" not in str(repo.events())


def test_workspaces_and_documents_rules(repo: LocalRepo) -> None:
    workspace = repo.add_workspace("C:/Docs", "Documentos", "auto_types", [".pdf", ".docx"])
    assert repo.workspaces() == [
        {"id": workspace, "root_path": "C:/Docs", "display_name": "Documentos",
         "new_file_policy": "auto_types", "auto_types": [".pdf", ".docx"]},
    ]  # fmt: skip
    with pytest.raises(ValidationFailed):
        repo.add_workspace("C:/Docs", "Outra")
    assert repo.propose(workspace, ".env", 1, 1.0, "") is None  # excluído: nem fica registado
    doc = repo.propose(workspace, "a/relatorio.txt", 1, 1.0, ".txt")
    assert doc is not None
    with pytest.raises(ValidationFailed):
        repo.propose(workspace, "a/relatorio.txt", 1, 1.0, ".txt")
    repo.set_classification(doc, "confidential")
    with pytest.raises(ValidationFailed):
        repo.set_classification(doc, "secreto")
    with pytest.raises(NotFound):
        repo.state("inexistente")
    with pytest.raises(NotFound):
        repo.apply("inexistente", Action.APPROVE)
    repo.remove_workspace(workspace)
    assert repo.workspaces() == []
    with pytest.raises(NotFound):
        repo.state(doc)  # os documentos saem com a pasta
