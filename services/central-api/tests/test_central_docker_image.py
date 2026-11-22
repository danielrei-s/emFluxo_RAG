"""Integração (marcador ``docker``; nightly e manual): a imagem da Central API constrói e é segura."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
IMAGE = "rag-central-api:test"
pytestmark = pytest.mark.docker


def _docker(*args: str, timeout: int = 600) -> str:
    done = subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=True, timeout=timeout
    )
    return done.stdout.strip()


@pytest.fixture(scope="module", autouse=True)
def image() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker não está instalado")
    _docker("build", "-q", "-f", "services/central-api/Dockerfile", "-t", IMAGE, str(ROOT))


def test_image_runs_as_non_root_with_a_healthcheck() -> None:
    assert _docker("image", "inspect", IMAGE, "--format", "{{.Config.User}}") == "10001"
    health = _docker("image", "inspect", IMAGE, "--format", "{{json .Config.Healthcheck.Test}}")
    assert "healthz" in health
    uid = _docker("run", "--rm", "--entrypoint", "id", IMAGE, "-u")
    assert uid == "10001"


def test_container_serves_healthz_with_a_read_only_filesystem() -> None:
    container = _docker("run", "-d", "--read-only", "--cap-drop", "ALL", IMAGE)
    try:
        probe = (
            "import time, urllib.request\n"
            "for _ in range(30):\n"
            "    try:\n"
            "        print(urllib.request.urlopen('http://127.0.0.1:8080/healthz').read().decode())\n"
            "        break\n"
            "    except OSError:\n"
            "        time.sleep(0.5)\n"
        )
        assert '"status":"ok"' in _docker("exec", container, "python", "-c", probe)
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)
