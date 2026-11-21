"""Testes de F0-T01: estrutura do repositório, .env.example, .gitignore e plano."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import check_structure  # noqa: E402

SECRET_NAME_RE = re.compile(r"KEY|SECRET|TOKEN|PASSWORD|DSN")


def test_required_dirs_exist() -> None:
    missing = [d for d in check_structure.REQUIRED_DIRS if not (ROOT / d).is_dir()]
    assert missing == []


def test_check_structure_reports_missing_dir(tmp_path: Path) -> None:
    assert check_structure.missing_dirs(tmp_path) == list(check_structure.REQUIRED_DIRS)


def test_env_example_has_no_secret_values() -> None:
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    variables = [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    assert variables, ".env.example não declara nenhuma variável"
    offenders = []
    for ln in variables:
        name, _, value = ln.partition("=")
        if SECRET_NAME_RE.search(name) and value.strip():
            offenders.append(name)
    assert offenders == []


def test_env_example_covers_c9_variables() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name in ("RAG_ENV", "RAG_DEPLOYMENT_MODE", "RAG_DATABASE_URL", "RAG_KEK_BASE64",
                 "RAG_OLLAMA_URL", "RAG_PROMPT_SENTINEL", "RAG_ALLOWED_LINK_DOMAINS"):
        assert re.search(rf"^{name}=", text, re.M), name


def test_gitignore_blocks_env_files() -> None:
    ignored = subprocess.run(["git", "check-ignore", "-q", ".env.local"], cwd=ROOT)
    assert ignored.returncode == 0
    example = subprocess.run(["git", "check-ignore", "-q", ".env.example"], cwd=ROOT)
    assert example.returncode == 1


def test_plan_and_spec_present() -> None:
    for rel in ("docs/plan/01-protocolo.md", "docs/plan/tarefas/F0-T01.md",
                "docs/spec/especificacao-v0.1.md", "docs/plan/STATUS.md",
                "docs/HUMAN_REQUESTS.md"):
        assert (ROOT / rel).is_file(), rel


def test_check_structure_script_exits_zero() -> None:
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_structure.py")],
                            cwd=ROOT, capture_output=True)
    assert result.returncode == 0
