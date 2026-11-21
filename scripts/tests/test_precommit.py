"""Testes de F0-T09: pre-commit e deteção de segredos (INV-13)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))


def _hook_ids() -> set[str]:
    return {hook["id"] for repo in CONFIG["repos"] for hook in repo["hooks"]}


def test_precommit_has_gitleaks_and_ruff() -> None:
    assert {"gitleaks", "ruff", "ruff-format"} <= _hook_ids()


def test_precommit_has_required_hygiene_hooks() -> None:
    required = {"prettier", "end-of-file-fixer", "trailing-whitespace", "check-yaml"}
    assert required <= _hook_ids()


def test_large_files_limit_is_500kb_and_corpus_is_exempt() -> None:
    hooks = [h for r in CONFIG["repos"] for h in r["hooks"] if h["id"] == "check-added-large-files"]
    assert len(hooks) == 1
    assert "--maxkb=500" in hooks[0]["args"]
    assert hooks[0]["exclude"] == "^fixtures/corpus/"


def test_make_hooks_installs_precommit() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "pre-commit install" in makefile


def _find_gitleaks() -> str | None:
    found = shutil.which("gitleaks")
    if found:
        return found
    cache = Path(os.environ.get("PRE_COMMIT_HOME", Path.home() / ".cache" / "pre-commit"))
    for pattern in ("*/golangenv-*/bin/gitleaks*", "*/golangenv-*/bin/gitleaks.exe"):
        for candidate in sorted(cache.glob(pattern)):
            if candidate.is_file():
                return str(candidate)
    return None


@pytest.fixture(scope="module")
def gitleaks() -> str:
    """Binário do gitleaks: PATH ou o instalado pelo pre-commit (``install-hooks``)."""
    binary = _find_gitleaks()
    if binary is None:
        subprocess.run(
            ["uv", "run", "pre-commit", "install-hooks"],
            cwd=ROOT,
            check=True,
        )
        binary = _find_gitleaks()
    assert binary is not None, "gitleaks não encontrado; corre `make hooks`"
    return binary


def _scan(binary: str, directory: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [binary, "dir", str(directory), "--no-banner", "--config", str(ROOT / ".gitleaks.toml")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_gitleaks_detects_fake_key(gitleaks: str, tmp_path: Path) -> None:
    # Chave falsa no formato AWS, montada em runtime para não aparecer no código-fonte.
    fake_key = "AKIA" + "QYLPMN5HHHFPZAM2"
    (tmp_path / "config.py").write_text(f'AWS_ACCESS_KEY_ID = "{fake_key}"\n', encoding="utf-8")
    result = _scan(gitleaks, tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr


def test_gitleaks_passes_clean_file(gitleaks: str, tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text('GREETING = "olá"\n', encoding="utf-8")
    assert _scan(gitleaks, tmp_path).returncode == 0
