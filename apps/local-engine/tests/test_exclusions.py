"""Testes de F11-T03: exclusões por omissão (segredos e ficheiros do sistema)."""

from __future__ import annotations

import pytest
from rag_local.exclusions import exclusion_reason, is_excluded

EXCLUDED = [
    ".env", ".ENV", "proj/.env.local", "certs/servidor.PEM", "a/b/chave.key", "x.p12", "x.PFX",
    "id_rsa", "id_rsa.pub", "id_ed25519", "cofre.kdbx", "Login.keychain-db", "wallet.dat",
    "minha.wallet", ".git/config", "repo/.GIT/HEAD", ".ssh/known_hosts", "web/node_modules/x/a.js",
    "src/__pycache__/m.pyc", ".venv/lib/x.py", "dados.sqlite", "app.db", "Atalho.LNK",
    "desktop.ini", "Thumbs.db", "pasta/.DS_Store", "C:\\Users\\x\\.ssh\\id_rsa",
]  # fmt: skip
ALLOWED = [
    "relatorio.pdf",
    "env.txt",
    "notas/ambiente.md",
    "keynote.pptx",
    "monkey.docx",
    "gitlog.txt",
    "docs/ssh-guia.pdf",
    "node_modules_notas.txt",
    "database.md",
    "wallet-guia.pdf",
    "",
]


@pytest.mark.parametrize("path", EXCLUDED)
def test_default_exclusions_match_and_reason(path: str) -> None:
    reason = exclusion_reason(path)
    assert reason and is_excluded(path), path


@pytest.mark.parametrize("path", ALLOWED)
def test_non_excluded_files_pass(path: str) -> None:
    assert exclusion_reason(path) is None and not is_excluded(path), path


def test_reasons_are_human_readable() -> None:
    assert exclusion_reason(".env") == "ficheiro de ambiente com segredos"
    assert exclusion_reason("a/.git/x") == "repositório de código"
    assert exclusion_reason("a/dados.db") == "base de dados"
