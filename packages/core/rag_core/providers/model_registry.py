"""Registo de modelos (F5-T02): aliases, licenças (INV-21) e revisões com hash (INV-22)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import field_validator, model_validator

from rag_core.errors import ValidationFailed
from rag_core.ids import sha256_file
from rag_core.types import Frozen

ALLOWED_LICENSES = frozenset({"apache-2.0", "mit", "bsd-2-clause", "bsd-3-clause"})
NEEDS_ADR_PREFIXES = ("llama", "gemma")  # licenças com restrições: só com ADR (C4)
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ModelFileSpec(Frozen):
    name: str
    sha256: str

    @field_validator("sha256")
    @classmethod
    def _hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("sha256 tem de ser hexadecimal minúsculo de 64 caracteres")
        return value


class ModelSpec(Frozen):
    """Entrada do ``models.yaml``."""

    kind: Literal["llm", "embedding", "reranker"]
    backend: str
    model: str
    license: str
    base_url_env: str | None = None
    api_key_env: str | None = None  # nome da definição com a chave (ex.: RAG_HF_API_KEY)
    revision: str | None = None
    files: tuple[ModelFileSpec, ...] = ()
    dim: int | None = None
    query_prefix: str = ""
    document_prefix: str = ""
    external: bool = False
    adr: str | None = None

    @model_validator(mode="after")
    def _rules(self) -> ModelSpec:
        license_id = self.license.strip().lower()
        if license_id not in ALLOWED_LICENSES:
            if license_id.startswith(NEEDS_ADR_PREFIXES):
                if not self.adr:
                    raise ValidationFailed(subcode="model_license_needs_adr")
            else:  # CC-BY-NC, "research only", desconhecidas…
                raise ValidationFailed(subcode="model_license_forbidden")
        if self.files and not self.revision:
            raise ValidationFailed(subcode="model_revision_missing")
        if self.kind == "embedding" and not self.dim:
            raise ValueError("modelos de embeddings precisam de dim")
        return self


class ModelRegistry:
    """Aliases → ``ModelSpec``, validados ao carregar."""

    def __init__(self, models: Mapping[str, ModelSpec]) -> None:
        self._models = dict(models)

    @classmethod
    def from_file(cls, path: Path) -> ModelRegistry:
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data.get("models"), dict):
            raise ValidationFailed(subcode="models_section_missing")
        specs = {alias: ModelSpec.model_validate(spec) for alias, spec in data["models"].items()}
        return cls(specs)

    @property
    def aliases(self) -> list[str]:
        return sorted(self._models)

    def get(self, alias: str) -> ModelSpec:
        try:
            return self._models[alias]
        except KeyError:
            raise ValidationFailed(subcode="unknown_model_alias") from None

    def verify_files(self, alias: str, base_dir: Path) -> list[Path]:
        """Compara o sha256 de cada ficheiro antes de o carregar (INV-22)."""
        paths = []
        for spec in self.get(alias).files:
            path = base_dir / spec.name
            if not path.is_file():
                raise ValidationFailed(subcode="model_file_missing")
            if sha256_file(path) != spec.sha256:
                raise ValidationFailed(subcode="model_hash_mismatch")
            paths.append(path)
        return paths
