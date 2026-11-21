"""Testes de F0-T10: workflows do GitHub Actions e Dependabot."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
SHA_RE = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml"))


def _steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for job in workflow["jobs"].values() for step in job["steps"]]


def _run_text(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_workflow_files_exist() -> None:
    assert {p.name for p in _workflow_files()} >= {"ci.yml", "nightly.yml"}


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_all_actions_pinned_by_sha(path: Path) -> None:
    uses = [s["uses"] for s in _steps(_load(path)) if "uses" in s]
    assert uses, "workflow sem nenhuma ação"
    unpinned = [u for u in uses if not u.startswith("./") and not SHA_RE.match(u)]
    assert unpinned == []
    # a versão fica em comentário ao lado de cada ação
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "uses:" in line:
            assert re.search(r"@[0-9a-f]{40}\s+#\s*v?\d", line), line


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_default_permissions_read_only(path: Path) -> None:
    assert _load(path)["permissions"] == {"contents": "read"}


def test_required_jobs_exist() -> None:
    ci = _load(WORKFLOWS / "ci.yml")
    assert {"python", "js", "security", "integration"} <= set(ci["jobs"])


def test_ci_runs_on_push_and_pull_request() -> None:
    triggers = _load(WORKFLOWS / "ci.yml")[True]  # a chave `on` é lida como booleano
    assert {"push", "pull_request"} <= set(triggers)


def test_python_job_runs_quality_tools_with_coverage() -> None:
    text = _run_text(_load(WORKFLOWS / "ci.yml")["jobs"]["python"])
    for needle in ("uv sync --all-packages", "ruff check", "mypy packages/core", "--cov"):
        assert needle in text


def test_js_job_uses_frozen_lockfile() -> None:
    text = _run_text(_load(WORKFLOWS / "ci.yml")["jobs"]["js"])
    assert "pnpm install --frozen-lockfile" in text
    for needle in ("pnpm -r lint", "pnpm -r typecheck", "pnpm -r test"):
        assert needle in text


def test_security_job_has_all_scanners() -> None:
    job = _load(WORKFLOWS / "ci.yml")["jobs"]["security"]
    text = _run_text(job)
    for needle in (
        "gitleaks-history",
        "semgrep scan",
        "--config p/default",
        "--config p/python",
        "--config p/typescript",
        "--error",
        "pip-audit",
        "pnpm audit --audit-level high",
        "make licenses",
    ):
        assert needle in text, needle
    assert any("anchore/sbom-action" in s.get("uses", "") for s in job["steps"])


def test_integration_job_treats_exit_code_5_as_success() -> None:
    text = _run_text(_load(WORKFLOWS / "ci.yml")["jobs"]["integration"])
    assert "-m integration" in text
    assert "--allow-hosts=127.0.0.1,localhost" in text
    assert "5" in text


def test_nightly_is_scheduled_and_runs_heavy_markers() -> None:
    nightly = _load(WORKFLOWS / "nightly.yml")
    triggers = nightly[True]
    assert "schedule" in triggers
    text = "\n".join(_run_text(job) for job in nightly["jobs"].values())
    for marker in ("slow", "docling", "ocr", "docker", "e2e"):
        assert marker in text


def test_dependabot_covers_required_ecosystems() -> None:
    config = _load(ROOT / ".github" / "dependabot.yml")
    ecosystems = {u["package-ecosystem"] for u in config["updates"]}
    assert {"uv", "npm", "github-actions", "docker", "cargo"} <= ecosystems


def test_gitleaks_allowlists_canaries_but_not_everything() -> None:
    text = (ROOT / ".gitleaks.toml").read_text(encoding="utf-8")
    for prefix in ("CANARIO-", "HIDDEN-", "PWNED-"):
        assert prefix in text
    assert "useDefault = true" in text
