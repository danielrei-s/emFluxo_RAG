"""Configuração tipada (C9).

Tudo com prefixo ``RAG_``; segredos como ``SecretStr`` (INV-13). Nenhum outro módulo lê
variáveis de ambiente diretamente: usam ``get_settings()`` ou recebem ``Settings`` injetadas.
"""

from __future__ import annotations

import enum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class Env(enum.StrEnum):
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PROD = "prod"


class DeploymentMode(enum.StrEnum):
    CLOUD = "cloud"
    HYBRID = "hybrid"
    OFFLINE = "offline"


class RetrievalSettings(BaseModel):
    """Parâmetros de recuperação."""

    model_config = ConfigDict(extra="forbid")

    k_vector: int = Field(default=30, ge=1)
    k_keyword: int = Field(default=30, ge=1)
    rrf_k: int = Field(default=60, ge=1)
    rerank_enabled: bool = True
    rerank_top_in: int = Field(default=20, ge=1)
    top_n: int = Field(default=6, ge=1)
    min_relevance: float = Field(default=0.35, ge=0.0, le=1.0)
    max_chunks_per_doc: int = Field(default=3, ge=1)
    injection_downweight: float = Field(default=0.5, ge=0.0, le=1.0)


class ChunkingSettings(BaseModel):
    """Parâmetros do chunker (em tokens aproximados)."""

    model_config = ConfigDict(extra="forbid")

    target_tokens: int = Field(default=500, ge=1)
    min_tokens: int = Field(default=300, ge=1)
    max_tokens: int = Field(default=800, ge=1)
    overlap_ratio: float = Field(default=0.12, ge=0.0, le=0.3)

    @model_validator(mode="after")
    def _check_token_bounds(self) -> Self:
        if not self.min_tokens < self.target_tokens < self.max_tokens:
            raise ValueError("chunking: é preciso min_tokens < target_tokens < max_tokens")
        return self


class LimitsSettings(BaseModel):
    """Limites de entrada."""

    model_config = ConfigDict(extra="forbid")

    max_question_chars: int = Field(default=2000, ge=1)
    max_upload_mb: int = Field(default=50, ge=1)
    max_history_messages: int = Field(default=6, ge=0)


def is_loopback_url(url: str) -> bool:
    """Indica se ``url`` aponta para ``127.0.0.1``, ``::1`` ou ``localhost`` (host exato)."""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return False
    return host in _LOOPBACK_HOSTS


class Settings(BaseSettings):
    """Definições da aplicação, lidas do ambiente (``RAG_*``) e de ``.env.local``."""

    model_config = SettingsConfigDict(
        env_prefix="RAG_",
        env_nested_delimiter="__",
        env_file=".env.local",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    env: Env = Env.DEV
    deployment_mode: DeploymentMode = DeploymentMode.CLOUD
    log_level: str = "INFO"
    log_tracebacks: bool = False

    # BD central (um utilizador por role); os URLs contêm credenciais.
    database_url: SecretStr | None = None
    database_worker_url: SecretStr | None = None
    database_backoffice_url: SecretStr | None = None
    database_migrator_url: SecretStr | None = None

    supabase_url: str | None = None
    supabase_jwks_url: str | None = None
    supabase_jwt_issuer: str | None = None
    supabase_jwt_audience: str | None = None
    supabase_service_role_key: SecretStr | None = None

    central_issuer: str | None = None
    central_signing_keys: SecretStr | None = None
    central_jwks_url: str | None = None
    central_api_url: str | None = None
    internal_api_key: SecretStr | None = None
    gateway_url: str | None = None

    models_file: Path | None = None
    gateway_policies_file: Path | None = None  # políticas por tenant do gateway (YAML)

    blob_backend: Literal["fs", "supabase", "s3"] = "fs"
    blob_fs_root: Path | None = None
    supabase_storage_bucket: str | None = None
    kek_base64: SecretStr | None = None

    redis_url: SecretStr | None = None
    sentry_dsn: SecretStr | None = None
    otel_exporter_otlp_endpoint: str | None = None

    local_data_dir: Path | None = None
    ollama_url: str | None = None

    prompt_sentinel: SecretStr | None = None
    allowed_link_domains: Annotated[list[str], NoDecode] = Field(default_factory=list)

    retrieval: RetrievalSettings = Field(default_factory=lambda: RetrievalSettings())
    chunking: ChunkingSettings = Field(default_factory=lambda: ChunkingSettings())
    limits: LimitsSettings = Field(default_factory=lambda: LimitsSettings())

    @field_validator("allowed_link_domains", mode="before")
    @classmethod
    def _split_domains(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @model_validator(mode="after")
    def _offline_requires_loopback_llm(self) -> Self:
        """INV-05: em modo offline nenhum URL de LLM pode sair da máquina."""
        if self.deployment_mode is DeploymentMode.OFFLINE:
            for name in ("ollama_url", "gateway_url"):
                url = getattr(self, name)
                if url is not None and not is_loopback_url(url):
                    raise ValueError(f"{name} tem de ser loopback em modo offline")
        return self

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> Self:
        """Lê o ambiente e ``env_file`` (``None`` desativa a leitura de ficheiros)."""
        return cls(_env_file=env_file)  # type: ignore[call-arg]

    @classmethod
    def for_tests(cls, **overrides: Any) -> Settings:
        """Settings só com valores por omissão e ``overrides``; ignora ambiente e ficheiros."""
        return _HermeticSettings(**overrides)


class _HermeticSettings(Settings):
    """Variante que só aceita valores passados no construtor (para testes)."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


@lru_cache
def get_settings() -> Settings:
    """Settings do processo (em cache)."""
    return Settings()
