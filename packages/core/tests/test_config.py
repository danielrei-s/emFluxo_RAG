"""Testes de ``rag_core.config`` (C9, INV-05, INV-13)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError
from rag_core.config import DeploymentMode, Env, Settings, get_settings

CORE_SRC = Path(__file__).resolve().parents[1] / "rag_core"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove qualquer variável RAG_ do ambiente real e limpa a cache."""
    import os

    for name in [n for n in os.environ if n.startswith("RAG_")]:
        monkeypatch.delenv(name)
    get_settings.cache_clear()


def test_defaults_match_c9() -> None:
    s = Settings.from_env()
    assert s.env is Env.DEV
    assert s.deployment_mode is DeploymentMode.CLOUD
    r = s.retrieval
    assert (r.k_vector, r.k_keyword, r.rrf_k) == (30, 30, 60)
    assert r.rerank_enabled is True
    assert (r.rerank_top_in, r.top_n, r.max_chunks_per_doc) == (20, 6, 3)
    assert (r.min_relevance, r.injection_downweight) == (0.35, 0.5)
    c = s.chunking
    assert (c.target_tokens, c.min_tokens, c.max_tokens) == (500, 300, 800)
    assert c.overlap_ratio == 0.12
    lim = s.limits
    assert (lim.max_question_chars, lim.max_upload_mb, lim.max_history_messages) == (2000, 50, 6)


def test_env_override_nested(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_RETRIEVAL__TOP_N", "4")
    monkeypatch.setenv("RAG_ENV", "staging")
    s = Settings.from_env()
    assert s.retrieval.top_n == 4
    assert s.retrieval.k_vector == 30
    assert s.env is Env.STAGING


def test_empty_env_values_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_ENV", "")
    monkeypatch.setenv("RAG_DATABASE_URL", "")
    s = Settings.from_env()
    assert s.env is Env.DEV
    assert s.database_url is None


def test_allowed_link_domains_parsed_from_comma_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_ALLOWED_LINK_DOMAINS", "example.com, docs.example.org ,")
    assert Settings.from_env().allowed_link_domains == ["example.com", "docs.example.org"]


def test_env_local_file_is_read(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text("RAG_LOG_LEVEL=DEBUG\n", encoding="utf-8")
    assert Settings.from_env(env_file).log_level == "DEBUG"


@pytest.mark.parametrize(
    "url",
    [
        "http://ollama:11434",
        "https://api.example.com/v1",
        "http://localhost.evil.com",
        "nonsense",
        "http://[::1",
    ],
)
def test_inv05_offline_rejects_remote_llm_url(url: str) -> None:
    with pytest.raises(ValidationError):
        Settings.for_tests(deployment_mode="offline", ollama_url=url)
    with pytest.raises(ValidationError):
        Settings.for_tests(deployment_mode="offline", gateway_url=url)


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434/v1"]
)
def test_inv05_offline_accepts_loopback_urls(url: str) -> None:
    s = Settings.for_tests(deployment_mode="offline", ollama_url=url, gateway_url=url)
    assert s.ollama_url == url


def test_remote_llm_url_allowed_outside_offline_mode() -> None:
    s = Settings.for_tests(deployment_mode="hybrid", ollama_url="http://ollama:11434")
    assert s.ollama_url == "http://ollama:11434"


def test_inv13_secrets_not_in_repr() -> None:
    secret = "CANARIO-segredo-123"  # noqa: S105
    s = Settings.for_tests(
        database_url=f"postgresql://u:{secret}@h/db",
        supabase_service_role_key=secret,
        internal_api_key=secret,
        kek_base64=secret,
        central_signing_keys=secret,
        prompt_sentinel=secret,
    )
    assert secret not in repr(s)
    assert secret not in str(s)
    assert secret not in s.model_dump_json()
    assert s.internal_api_key is not None
    assert s.internal_api_key.get_secret_value() == secret


@pytest.mark.parametrize(
    "chunking",
    [
        {"min_tokens": 500, "target_tokens": 500, "max_tokens": 800},
        {"min_tokens": 300, "target_tokens": 800, "max_tokens": 800},
        {"min_tokens": 600, "target_tokens": 500, "max_tokens": 800},
        {"overlap_ratio": 0.31},
        {"overlap_ratio": -0.01},
    ],
)
def test_invalid_chunking_rejected(chunking: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        Settings.for_tests(chunking=chunking)


def test_invalid_enum_value_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.for_tests(env="production")


def test_for_tests_ignores_ambient_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_ENV", "prod")
    assert Settings.for_tests().env is Env.DEV
    assert Settings.for_tests(env="test").env is Env.TEST


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_LOG_LEVEL", "WARNING")
    first = get_settings()
    monkeypatch.setenv("RAG_LOG_LEVEL", "ERROR")
    assert get_settings() is first
    assert first.log_level == "WARNING"


def test_no_other_module_reads_environ_directly() -> None:
    pattern = re.compile(r"os\.environ|os\.getenv|getenv\(")
    offenders = [
        str(path.relative_to(CORE_SRC))
        for path in CORE_SRC.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
