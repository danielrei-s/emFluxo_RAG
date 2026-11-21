"""Testes de F0-T11: compose de desenvolvimento (INV-24)."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "infra" / "compose" / "docker-compose.dev.yml"
COMPOSE: dict[str, Any] = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
SERVICES: dict[str, dict[str, Any]] = COMPOSE["services"]


def _published_ports() -> list[tuple[str, str]]:
    return [(name, str(port)) for name, svc in SERVICES.items() for port in svc.get("ports", [])]


def test_inv24_all_published_ports_bind_localhost() -> None:
    ports = _published_ports()
    assert ports, "nenhuma porta publicada"
    assert [(n, p) for n, p in ports if not p.startswith("127.0.0.1:")] == []


def test_inv24_ollama_is_published_only_on_loopback() -> None:
    ports = SERVICES["ollama"]["ports"]
    assert ports == ["127.0.0.1:11434:11434"]


def test_images_pinned() -> None:
    for name, svc in SERVICES.items():
        image = svc["image"]
        assert ":" in image, f"{name}: imagem sem tag"
        tag = image.rsplit(":", 1)[1]
        assert tag != "latest", f"{name}: tag latest"
        assert re.search(r"\d+\.\d+", tag), f"{name}: a tag deve ter uma versão fixa ({tag})"


def test_postgres_is_pgvector_pg17() -> None:
    postgres = SERVICES["postgres"]
    assert postgres["image"].startswith("pgvector/pgvector:")
    assert postgres["image"].endswith("-pg17")
    assert postgres["ports"] == ["127.0.0.1:54329:5432"]
    assert "pg_isready" in " ".join(postgres["healthcheck"]["test"])
    assert postgres["volumes"], "o postgres precisa de volume"


def test_optional_services_use_profiles() -> None:
    assert "profiles" not in SERVICES["postgres"]
    assert SERVICES["redis"]["profiles"] == ["redis"]
    assert SERVICES["ollama"]["profiles"] == ["llm"]
    assert SERVICES["mailpit"]["profiles"] == ["mail"]
    assert "127.0.0.1:8025:8025" in SERVICES["mailpit"]["ports"]


def test_llm_gpu_profile_reserves_nvidia_gpu() -> None:
    gpu = SERVICES["ollama-gpu"]
    assert gpu["profiles"] == ["llm-gpu"]
    devices = gpu["deploy"]["resources"]["reservations"]["devices"]
    assert devices[0]["driver"] == "nvidia"
    assert "gpu" in devices[0]["capabilities"]
    assert gpu["ports"] == ["127.0.0.1:11434:11434"]


def test_smoke_script_waits_for_health_and_creates_vector_extension() -> None:
    script = (ROOT / "scripts" / "compose_smoke.sh").read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS vector" in script
    assert "healthy" in script
    assert script.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in script


def test_make_up_and_down_use_dev_compose_file() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "docker-compose.dev.yml" in makefile
    assert "ainda não implementado (F0-T11)" not in makefile


@pytest.mark.docker
def test_compose_up_and_smoke() -> None:
    """Integração: precisa de Docker; corre em nightly e manualmente."""
    if shutil.which("docker") is None:
        pytest.fail("docker não encontrado")
    make = shutil.which("make") or "make"
    bash = shutil.which("bash") or "bash"
    try:
        subprocess.run([make, "up"], cwd=ROOT, check=True)
        subprocess.run([bash, "scripts/compose_smoke.sh"], cwd=ROOT, check=True)
    finally:
        subprocess.run([make, "down"], cwd=ROOT, check=False)
