"""Testes de F6-T08: fornecedor Hugging Face (fallback externo e opcional)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import SecretStr
from rag_core.config import Settings
from rag_core.errors import ValidationFailed
from rag_core.providers.factory import build_llm_providers
from rag_core.providers.model_registry import ModelRegistry
from rag_core.providers.openai_compat import OpenAICompatibleLLM
from rag_core.types import ChatMessage, GenerationParams

EXAMPLE = Path(__file__).resolve().parents[3] / "models.example.yaml"
HF_URL = os.environ.get("RAG_LIVE_HF_URL")
HF_KEY = os.environ.get("RAG_LIVE_HF_KEY")


def test_hf_alias_marked_external() -> None:
    spec = ModelRegistry.from_file(EXAMPLE).get("rag-fallback-hf")
    assert spec.external is True and spec.kind == "llm"
    settings = Settings.for_tests(
        ollama_url="http://ollama:11434/v1",
        hf_endpoint_url="https://hf.test/v1",
        hf_api_key=SecretStr("segredo-hf"),
    )
    providers = build_llm_providers(settings, EXAMPLE)
    assert providers["rag-fallback-hf"].is_remote is True  # => o gateway redige a PII
    assert providers["rag-default"].is_remote is False
    assert "segredo-hf" not in repr(providers["rag-fallback-hf"])  # INV-13


def test_hf_alias_needs_endpoint_and_key() -> None:
    base = {"ollama_url": "http://ollama:11434/v1"}
    with pytest.raises(ValidationFailed) as no_url:
        build_llm_providers(Settings.for_tests(**base), EXAMPLE)
    assert no_url.value.subcode == "model_base_url_missing"
    with pytest.raises(ValidationFailed) as no_key:
        build_llm_providers(
            Settings.for_tests(**base, hf_endpoint_url="https://hf.test/v1"), EXAMPLE
        )
    assert no_key.value.subcode == "model_api_key_missing"


@pytest.mark.live
@pytest.mark.enable_socket
@pytest.mark.skipif(not (HF_URL and HF_KEY), reason="RAG_LIVE_HF_URL/RAG_LIVE_HF_KEY não definidos")
def test_hf_endpoint_live_roundtrip() -> None:
    assert HF_URL and HF_KEY
    llm = OpenAICompatibleLLM(
        "hf-live", HF_URL, "tgi", api_key=SecretStr(HF_KEY), timeout_s=300, is_remote=True
    )
    messages = [ChatMessage(role="user", content="Responde apenas com a palavra: ok")]
    result = llm.generate(messages, params=GenerationParams(max_tokens=20, temperature=0.0))
    assert result.text.strip()
