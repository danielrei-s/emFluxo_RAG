"""Testes de F6-T07: montagem das dependências do gateway a partir das Settings."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rag_core.config import Settings
from rag_core.errors import ValidationFailed
from rag_gateway.app import create_app
from rag_gateway.ports import NoDevices, NoPrincipals
from rag_gateway.wiring import build_deps

pytestmark = pytest.mark.enable_socket

MODELS = """
models:
  rag-default:
    kind: llm
    backend: openai_compat
    model: llama
    license: MIT
    base_url_env: RAG_OLLAMA_URL
  rag-embed:
    kind: embedding
    backend: openai_compat
    model: embed
    license: MIT
    base_url_env: RAG_OLLAMA_URL
    dim: 4
"""


def test_nothing_configured_is_alive_but_not_ready() -> None:
    deps = build_deps(Settings.for_tests())
    assert deps.authenticator is None and deps.chat is None
    client = TestClient(create_app(Settings.for_tests(), deps))
    assert client.get("/healthz").status_code == 200
    ready = client.get("/readyz")
    assert ready.status_code == 503 and ready.json()["checks"] == {"auth": False, "chat": False}


def test_fully_configured(tmp_path: Path) -> None:
    models = tmp_path / "models.yaml"
    models.write_text(MODELS, encoding="utf-8")
    policies = tmp_path / "policies.yaml"
    policies.write_text("tenants:\n  t1:\n    allowed_models: [rag-default]\n", encoding="utf-8")
    settings = Settings.for_tests(
        central_issuer="https://central.test",
        central_jwks_url="https://central.test/jwks.json",
        models_file=models,
        gateway_policies_file=policies,
        ollama_url="http://ollama:11434/v1",
    )
    deps = build_deps(settings)
    assert deps.authenticator is not None and deps.chat is not None
    client = TestClient(create_app(settings, deps))
    assert client.get("/readyz").json() == {
        "status": "ready",
        "checks": {"auth": True, "chat": True},
    }
    assert deps.chat.policies.get("t1").allowed_models == ("rag-default",)


def test_policies_without_models_fails_fast(tmp_path: Path) -> None:
    policies = tmp_path / "policies.yaml"
    policies.write_text("tenants: {}\n", encoding="utf-8")
    settings = Settings.for_tests(
        gateway_policies_file=policies, models_file=tmp_path / "nao-existe.yaml"
    )
    with pytest.raises(ValidationFailed):
        build_deps(settings)


def test_without_central_api_no_user_or_device_is_accepted() -> None:
    assert NoDevices().is_active("t", "u", "d") is False
    assert NoPrincipals().resolve({"sub": "x"}, "d") is None
