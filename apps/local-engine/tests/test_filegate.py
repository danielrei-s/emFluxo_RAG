"""Testes de F11-T04: FileGate (raízes, caminhos, listagem sem ler e leitura só de aprovados)."""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from rag_core.errors import ConsentError, FileTooLarge, ValidationFailed
from rag_local.consent import Action
from rag_local.filegate import FileGate
from rag_local.repo import LocalRepo

SRC = Path(__file__).resolve().parents[1] / "rag_local"


@pytest.fixture
def repo() -> LocalRepo:
    return LocalRepo(sqlite3.connect(":memory:"))


@pytest.fixture
def gate(repo: LocalRepo) -> FileGate:
    return FileGate(repo)


def _workspace(gate: FileGate, repo: LocalRepo, root: Path) -> str:
    return repo.add_workspace(gate.register_root(str(root)), "Teste")


def _tree(root: Path) -> None:
    (root / "sub").mkdir()
    (root / "a.txt").write_text("conteúdo A", encoding="utf-8")
    (root / "sub" / "b.md").write_text("conteúdo B", encoding="utf-8")
    (root / ".env").write_text("SEGREDO=1", encoding="utf-8")
    (root / "chave.pem").write_text("-----", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("x", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "m.js").write_text("x", encoding="utf-8")


def test_register_root_rules(gate: FileGate, tmp_path: Path) -> None:
    assert gate.register_root(str(tmp_path)) == os.path.realpath(tmp_path)
    for bad, subcode in (
        (str(tmp_path / "nao-existe"), "not_a_directory"),
        (os.path.abspath(os.sep), "filesystem_root"),
        (str(Path.home()), "home_folder"),
        ("\\\\?\\C:\\Users", "device_path"),
        ("\\\\.\\PhysicalDrive0", "device_path"),
    ):
        with pytest.raises(ValidationFailed) as exc:
            gate.register_root(bad)
        assert exc.value.subcode == subcode, bad
    assert gate.register_root(str(Path.home()), allow_home=True)  # só com autorização explícita
    system = "C:\\Windows" if sys.platform == "win32" else "/etc"
    if os.path.isdir(system):
        with pytest.raises(ValidationFailed) as exc:
            gate.register_root(system)
        assert exc.value.subcode == "system_folder"


def test_excluded_file_never_listed(gate: FileGate, repo: LocalRepo, tmp_path: Path) -> None:
    _tree(tmp_path)
    workspace = _workspace(gate, repo, tmp_path)
    listed = gate.list_files(workspace)
    assert [f.rel_path for f in listed] == ["a.txt", "sub/b.md"]
    assert (listed[0].name, listed[0].ext, listed[0].size) == (
        "a.txt",
        ".txt",
        len("conteúdo A".encode()),
    )
    with pytest.raises(ValidationFailed):
        gate.list_files("inexistente")


def test_inv10_dotdot_rejected(gate: FileGate, repo: LocalRepo, tmp_path: Path) -> None:
    root = tmp_path / "raiz"
    root.mkdir()
    (tmp_path / "fora.txt").write_text("x", encoding="utf-8")
    workspace = _workspace(gate, repo, root)
    for rel in ("../fora.txt", "a/../../fora.txt", "..\\fora.txt", "/etc/passwd", "", "C:\\x.txt"):
        with pytest.raises(ValidationFailed):
            gate.resolve(workspace, rel)


def test_ads_and_reserved_names_rejected(gate: FileGate, repo: LocalRepo, tmp_path: Path) -> None:
    workspace = _workspace(gate, repo, tmp_path)
    for rel in (
        "a.txt:segredo",
        "a.txt::$DATA",
        "CON",
        "nul.txt",
        "sub/AUX.log",
        "com1",
        "LPT9.md",
    ):
        with pytest.raises(ValidationFailed):
            gate.resolve(workspace, rel)
    assert gate.resolve(workspace, "console.txt").name == "console.txt"


@pytest.mark.posix_only
@pytest.mark.skipif(sys.platform == "win32", reason="symlinks POSIX")
def test_inv10_symlink_escape_rejected(gate: FileGate, repo: LocalRepo, tmp_path: Path) -> None:
    root, outside = tmp_path / "raiz", tmp_path / "fora"
    root.mkdir()
    outside.mkdir()
    (outside / "segredo.txt").write_text("x", encoding="utf-8")
    (root / "atalho").symlink_to(outside)
    (root / "ficheiro").symlink_to(outside / "segredo.txt")
    workspace = _workspace(gate, repo, root)
    for rel in ("atalho/segredo.txt", "ficheiro"):
        with pytest.raises(ValidationFailed) as exc:
            gate.resolve(workspace, rel)
        assert exc.value.subcode == "path_escape"
    assert gate.list_files(workspace) == []  # atalhos nunca são seguidos nem listados


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="junctions Windows")
def test_inv10_junction_escape_rejected(gate: FileGate, repo: LocalRepo, tmp_path: Path) -> None:
    root, outside = tmp_path / "raiz", tmp_path / "fora"
    root.mkdir()
    outside.mkdir()
    (outside / "segredo.txt").write_text("x", encoding="utf-8")
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(root / "juncao"), str(outside)],
        check=True, capture_output=True,
    )  # fmt: skip
    workspace = _workspace(gate, repo, root)
    with pytest.raises(ValidationFailed) as exc:
        gate.resolve(workspace, "juncao/segredo.txt")
    assert exc.value.subcode == "path_escape"
    assert gate.list_files(workspace) == []


def test_reading_pending_doc_denied(gate: FileGate, repo: LocalRepo, tmp_path: Path) -> None:
    _tree(tmp_path)
    workspace = _workspace(gate, repo, tmp_path)
    meta = gate.list_files(workspace)[0]
    doc = repo.propose(workspace, meta.rel_path, meta.size, meta.mtime, meta.ext)
    assert doc is not None
    with pytest.raises(ConsentError, match="not_approved"):  # pendente
        gate.read_bytes(doc, 1000)
    repo.apply(doc, Action.REJECT)
    with pytest.raises(ConsentError):
        gate.read_bytes(doc, 1000)
    repo.apply(doc, Action.APPROVE)
    data, changed = gate.read_bytes(doc, 1000)
    assert data == "conteúdo A".encode() and changed is False
    repo.apply(doc, Action.REVOKE)
    with pytest.raises(ConsentError):  # revogado volta a ser inacessível
        gate.read_bytes(doc, 1000)


def test_read_detects_changes_and_size_limit(
    gate: FileGate, repo: LocalRepo, tmp_path: Path
) -> None:
    (tmp_path / "a.txt").write_text("um", encoding="utf-8")
    workspace = _workspace(gate, repo, tmp_path)
    meta = gate.list_files(workspace)[0]
    doc = repo.propose(workspace, meta.rel_path, meta.size, meta.mtime, meta.ext)
    assert doc is not None
    repo.apply(doc, Action.APPROVE)
    (tmp_path / "a.txt").write_text("um texto maior", encoding="utf-8")
    data, changed = gate.read_bytes(doc, 1000)
    assert data == b"um texto maior" and changed is True  # mudou: pede re-hash
    with pytest.raises(FileTooLarge):
        gate.read_bytes(doc, 3)


def test_unknown_workspace_and_excluded_documents(
    gate: FileGate, repo: LocalRepo, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text("X=1", encoding="utf-8")
    workspace = _workspace(gate, repo, tmp_path)
    assert repo.propose(workspace, ".env", 3, 1.0, "") is None  # nunca chega a ser proposto
    with pytest.raises(ValidationFailed):
        gate.resolve("inexistente", "a.txt")


def test_no_user_file_access_outside_filegate() -> None:
    """DoD: só ``filegate.py`` abre ficheiros; o resto do motor recebe bytes."""
    offenders = []
    for path in SRC.glob("*.py"):
        if path.name == "filegate.py":
            continue
        text = path.read_text(encoding="utf-8")
        forbidden = r"(?<![\w.])open\(|\.read_text\(|\.open\(|os\.scandir\(|(?<!gate)\.read_bytes\("
        if re.search(forbidden, text):
            offenders.append(path.name)
    assert offenders == []


def test_inv10_indexing_opens_only_allowed_paths(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    _tree(root)
    harness = Path(__file__).parent / "helpers" / "audit_harness.py"
    result = subprocess.run(
        [sys.executable, str(harness), str(root)], capture_output=True, text=True, check=True,
    )  # fmt: skip
    import json

    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["listed"] == ["a.txt", "sub/b.md"]
    real_root = os.path.realpath(root)

    def inside_workspace(p: str) -> bool:
        return os.path.normcase(p).startswith(os.path.normcase(real_root) + os.sep)

    assert [p for p in report["opened"]["list"] if inside_workspace(p)] == []  # listar não abre
    read = [p for p in report["opened"]["read"] if inside_workspace(p)]
    assert sorted(os.path.basename(p) for p in read) == ["a.txt", "b.md"]  # só os aprovados
    repo_root = Path(__file__).resolve().parents[3]
    allowed = [
        real_root, os.path.realpath(sys.prefix), os.path.realpath(sys.base_prefix),
        os.path.realpath(os.path.join(repo_root, "apps", "local-engine")),
        os.path.realpath(os.path.join(repo_root, "packages", "core")),
        os.path.realpath(tempfile_dir()),
    ]  # fmt: skip
    outside = [
        p for phase in report["opened"].values() for p in phase
        if not any(os.path.normcase(p).startswith(os.path.normcase(a)) for a in allowed)
    ]  # fmt: skip
    assert outside == [], outside
    assert not any(".env" in os.path.basename(p) or p.endswith(".pem") for p in read)


def tempfile_dir() -> str:
    import tempfile

    return tempfile.gettempdir()
