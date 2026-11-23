"""Testes de F11-T05: fluxo de consentimento completo pela API local (INV-10, INV-18)."""

from __future__ import annotations

import builtins
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from rag_core.fakes import FakeEmbedder
from rag_core.stores import SqliteVectorStore
from rag_core.testing.chunks import make_chunk
from rag_local.app import create_app
from rag_local.filegate import FileGate
from rag_local.repo import LocalRepo
from rag_local.state import LOCAL_TENANT, LocalState

pytestmark = pytest.mark.enable_socket
TOKEN = "token-de-teste-0123456789"
PORT = 49152
DIM = FakeEmbedder().dim


class Env:
    def __init__(self) -> None:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.repo = LocalRepo(conn)
        self.store = SqliteVectorStore(
            lambda: sqlite3.connect(":memory:", check_same_thread=False), DIM
        )
        self.state = LocalState(self.repo, FileGate(self.repo), self.store)
        app = create_app(token=TOKEN, port=PORT, local=self.state)
        self.client = TestClient(
            app, base_url=f"http://127.0.0.1:{PORT}", raise_server_exceptions=False
        )

    def call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response: httpx.Response = self.client.request(
            method, f"/v1{path}", headers={"Authorization": f"Bearer {TOKEN}"}, **kwargs
        )
        return response


@pytest.fixture
def env() -> Iterator[Env]:
    yield Env()


def _folder(root: Path) -> Path:
    (root / "RH").mkdir(parents=True)
    (root / "a.txt").write_text("conteúdo A", encoding="utf-8")
    (root / "b.pdf").write_bytes(b"%PDF-1.4")
    (root / "RH" / "salario.xlsx").write_bytes(b"xlsx")
    (root / "imagem.png").write_bytes(b"png")
    (root / ".env").write_text("SEGREDO=1", encoding="utf-8")
    return root


def _create(env: Env, root: Path) -> str:
    response = env.call("POST", "/workspaces", json={"path": str(root)})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_preview_reads_no_file_content(
    env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _folder(tmp_path / "docs")
    opened: list[str] = []
    real_open = builtins.open

    def spy(file: Any, *args: Any, **kwargs: Any) -> Any:
        if str(file).startswith(str(root)):
            opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    workspace = _create(env, root)
    files = env.call("GET", f"/workspaces/{workspace}/files").json()
    assert opened == []  # a pré-visualização só lê metadados
    by_name = {f["name"]: f for f in files}
    assert by_name[".env"]["state"] == "excluded" and by_name[".env"]["excluded_reason"]
    assert by_name["salario.xlsx"]["suggested_classification"] == "restricted"
    assert by_name["a.txt"]["state"] == "pending" and by_name["a.txt"]["doc_id"]


def test_full_consent_flow_temp_folder(env: Env, tmp_path: Path) -> None:
    root = _folder(tmp_path / "docs")
    created = env.call("POST", "/workspaces", json={"path": str(root)}).json()
    workspace = created["id"]
    assert created["files"] == 4  # o .env nunca é proposto
    assert [w["id"] for w in env.call("GET", "/workspaces").json()] == [workspace]
    pending = env.call("GET", f"/workspaces/{workspace}/files", params={"state": "pending"}).json()
    assert len(pending) == 4
    ids = {f["name"]: f["doc_id"] for f in pending}
    approved = env.call(
        "POST", f"/workspaces/{workspace}/approve", json={"doc_ids": [ids["a.txt"]]}
    )
    assert approved.json() == {"approved": 1, "skipped": 0}
    again = env.call("POST", f"/workspaces/{workspace}/approve", json={"doc_ids": [ids["a.txt"]]})
    assert again.json() == {"approved": 0, "skipped": 1}
    rest = env.call(
        "POST",
        f"/workspaces/{workspace}/approve",
        json={"all_supported": True, "except": [ids["b.pdf"]]},
    )
    assert rest.json() == {"approved": 1, "skipped": 1}  # salario.xlsx; imagem.png não é suportada
    assert env.call("POST", f"/documents/{ids['b.pdf']}/reject").json() == {"state": "rejected"}
    states = {
        f["name"]: f["state"] for f in env.call("GET", f"/workspaces/{workspace}/files").json()
    }
    assert states == {
        "a.txt": "approved", "b.pdf": "rejected", "salario.xlsx": "approved",
        "imagem.png": "pending", ".env": "excluded",
    }  # fmt: skip
    unknown = env.call("POST", f"/workspaces/{workspace}/approve", json={"doc_ids": ["x"]})
    assert unknown.status_code == 422


def test_approve_enqueues_indexing(env: Env, tmp_path: Path) -> None:
    root = _folder(tmp_path / "docs")
    workspace = _create(env, root)
    docs = {d["rel_path"]: d["doc_id"] for d in env.repo.documents(workspace)}
    env.call(
        "POST", f"/workspaces/{workspace}/approve", json={"doc_ids": [docs["a.txt"], docs["b.pdf"]]}
    )
    jobs = env.repo.jobs()
    assert [(j["kind"], j["doc_id"]) for j in jobs] == [
        ("index", docs["a.txt"]),
        ("index", docs["b.pdf"]),
    ]
    env.call(
        "POST", f"/documents/{docs['a.txt']}/reject"
    )  # rejeitar (já aprovado) falha: sem tocar
    assert len(env.repo.jobs()) == 2


def test_inv18_revoke_removes_chunks_immediately(env: Env, tmp_path: Path) -> None:
    workspace = _create(env, _folder(tmp_path / "docs"))
    doc = next(d["doc_id"] for d in env.repo.documents(workspace) if d["rel_path"] == "a.txt")
    env.call("POST", f"/workspaces/{workspace}/approve", json={"doc_ids": [doc]})
    env.state.store.upsert([make_chunk("texto", doc_id=doc, tenant_id=LOCAL_TENANT)])
    assert env.state.store.document_hashes(LOCAL_TENANT, "w1") != {}
    revoked = env.call("POST", f"/documents/{doc}/revoke")
    assert revoked.json() == {"state": "revoked", "chunks_removed": 1}
    assert env.state.store.document_hashes(LOCAL_TENANT, "w1") == {}
    assert env.repo.jobs() == []
    assert env.call("POST", f"/documents/{doc}/revoke").status_code == 403  # já revogado


def test_local_only_patch_persisted(env: Env, tmp_path: Path) -> None:
    workspace = _create(env, _folder(tmp_path / "docs"))
    doc = next(d["doc_id"] for d in env.repo.documents(workspace) if d["rel_path"] == "a.txt")
    assert env.repo.documents(workspace)[0]["local_only"] is True  # por omissão nada sai
    assert (
        env.call(
            "PATCH", f"/documents/{doc}", json={"local_only": False, "classification": "public"}
        ).status_code
        == 200
    )
    stored = next(d for d in env.repo.documents(workspace) if d["doc_id"] == doc)
    assert (stored["local_only"], stored["classification"]) == (False, "public")
    assert env.call("PATCH", f"/documents/{doc}", json={}).status_code == 422
    assert (
        env.call("PATCH", f"/documents/{doc}", json={"classification": "secreto"}).status_code
        == 422
    )
    assert env.call("PATCH", "/documents/nao-existe", json={"local_only": True}).status_code == 404


def test_delete_workspace_removes_everything_but_events(env: Env, tmp_path: Path) -> None:
    workspace = _create(env, _folder(tmp_path / "docs"))
    doc = env.repo.documents(workspace)[0]["doc_id"]
    env.call("POST", f"/workspaces/{workspace}/approve", json={"doc_ids": [doc]})
    env.state.store.upsert([make_chunk("texto", doc_id=doc, tenant_id=LOCAL_TENANT)])
    removed = env.call("DELETE", f"/workspaces/{workspace}")
    assert removed.json() == {"chunks_removed": 1}
    assert env.call("GET", "/workspaces").json() == []
    assert env.repo.documents(workspace) == [] and env.repo.jobs() == []
    actions = [e["action"] for e in env.repo.events()]
    assert "approve" in actions and "workspace_remove" in actions  # os eventos ficam


def test_workspace_policy_and_validation(env: Env, tmp_path: Path) -> None:
    workspace = _create(env, _folder(tmp_path / "docs"))
    ok = env.call(
        "PATCH",
        f"/workspaces/{workspace}",
        json={"new_file_policy": "auto_types", "auto_types": [".PDF", ".txt"]},
    )
    assert ok.status_code == 200
    assert env.repo.workspaces()[0]["auto_types"] == [".pdf", ".txt"]
    for bad in ({"new_file_policy": "sempre"}, {"new_file_policy": "auto_types", "auto_types": ["pdf"]},
                {"new_file_policy": "ask", "auto_types": [".exe"]}):  # fmt: skip
        assert env.call("PATCH", f"/workspaces/{workspace}", json=bad).status_code == 422
    assert (
        env.call("PATCH", "/workspaces/inexistente", json={"new_file_policy": "ask"}).status_code
        == 404
    )
    assert (
        env.call("POST", "/workspaces", json={"path": str(tmp_path / "nao-existe")}).status_code
        == 422
    )
    assert env.call("POST", "/workspaces", json={"path": str(tmp_path), "x": 1}).status_code == 422
    unauthenticated = env.client.get("/v1/workspaces")
    assert unauthenticated.status_code == 401
    unconfigured = TestClient(
        create_app(token=TOKEN, port=PORT), base_url=f"http://127.0.0.1:{PORT}"
    )
    assert (
        unconfigured.get("/v1/workspaces", headers={"Authorization": f"Bearer {TOKEN}"}).status_code
        == 404
    )
