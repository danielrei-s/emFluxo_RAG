"""Testes de F6-T07: compose de produção da Máquina 1 (INV-13, INV-24)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "infra" / "compose" / "docker-compose.prod.yml"
COMPOSE: dict[str, Any] = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
SERVICES: dict[str, dict[str, Any]] = COMPOSE["services"]
ROOT_EXCEPTIONS = {"ollama"}  # a imagem oficial escreve em /root/.ollama (justificado no ficheiro)
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|DATABASE_URL)", re.I)


def test_expected_services() -> None:
    assert set(SERVICES) == {"gateway", "ollama", "cloudflared"}


def test_inv24_ollama_has_no_ports_and_internal_network_only() -> None:
    ollama = SERVICES["ollama"]
    assert "ports" not in ollama and "expose" not in ollama
    assert ollama["networks"] == ["models"]
    assert COMPOSE["networks"]["models"]["internal"] is True
    assert "internal" not in COMPOSE["networks"]["edge"]
    assert set(SERVICES["gateway"]["networks"]) == {"edge", "models"}
    assert SERVICES["cloudflared"]["networks"] == ["edge"]


def test_inv24_nothing_is_published_on_the_host() -> None:
    assert [name for name, svc in SERVICES.items() if "ports" in svc] == []
    assert all(svc.get("network_mode") not in {"host"} for svc in SERVICES.values())


def test_services_hardened() -> None:
    for name, svc in SERVICES.items():
        assert svc["read_only"] is True, name
        assert svc["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in svc["security_opt"], name
        assert svc["restart"] == "unless-stopped", name
        assert not svc.get("privileged"), name
        assert "cap_add" not in svc, name
        if name not in ROOT_EXCEPTIONS:
            uid = str(svc["user"]).split(":")[0]
            assert uid.isdigit() and int(uid) > 0, f"{name}: tem de correr sem ser root"


def test_inv13_no_inline_secrets() -> None:
    for name, svc in SERVICES.items():
        for key, value in (svc.get("environment") or {}).items():
            assert not SECRET_NAME.search(key), f"{name}: {key} parece um segredo inline"
            assert "://" not in str(value) or "@" not in str(value), f"{name}: credenciais no URL"
    for name in ("gateway", "cloudflared"):
        env_file = SERVICES[name]["env_file"]
        assert str(env_file).startswith("/etc/rag/"), name  # fora do repositório
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    assert "TUNNEL_TOKEN=" not in text and "eyJ" not in text


def test_images_pinned() -> None:
    for name, svc in SERVICES.items():
        image = svc["image"]
        assert ":" in image, f"{name}: imagem sem tag"
        tag = image.rsplit(":", 1)[1]
        assert tag != "latest" and re.fullmatch(r"[0-9][0-9A-Za-z.\-]*", tag), f"{name}: {tag}"


def test_gateway_configuration_points_at_the_internal_ollama() -> None:
    env = SERVICES["gateway"]["environment"]
    assert env["RAG_OLLAMA_URL"] == "http://ollama:11434/v1"
    mounts = SERVICES["gateway"]["volumes"]
    assert all(m.endswith(":ro") for m in mounts)
    assert SERVICES["gateway"]["build"]["dockerfile"] == "services/gateway/Dockerfile"


def test_start_order_waits_for_health() -> None:
    assert SERVICES["gateway"]["depends_on"]["ollama"]["condition"] == "service_healthy"
    assert SERVICES["cloudflared"]["depends_on"]["gateway"]["condition"] == "service_healthy"
    assert "healthcheck" in SERVICES["ollama"]


def test_ollama_reserves_the_gpu() -> None:
    devices = SERVICES["ollama"]["deploy"]["resources"]["reservations"]["devices"]
    assert devices[0]["driver"] == "nvidia" and "gpu" in devices[0]["capabilities"]
