"""Módulos por tenant (F9-T02; INV-19, INV-20): manifestos validados e config com JSON Schema.

O núcleo não conhece nenhum módulo concreto (INV-20): só lê manifestos de uma pasta ``modules/``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
from pydantic import ConfigDict, Field, ValidationError, field_validator

from rag_core.errors import ValidationFailed
from rag_core.types import Frozen

_NAME = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$")


class ModuleManifest(Frozen):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: str
    description: str = Field(min_length=1, max_length=200)
    ui_routes: tuple[str, ...] = ()
    api_prefix: str
    permissions: tuple[str, ...] = ()
    config_schema: dict[str, Any]
    default_enabled: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not _NAME.fullmatch(value):
            raise ValueError("kebab_case")
        return value

    @field_validator("version")
    @classmethod
    def _version(cls, value: str) -> str:
        if not _SEMVER.fullmatch(value):
            raise ValueError("semver")
        return value

    @field_validator("api_prefix")
    @classmethod
    def _prefix(cls, value: str) -> str:
        if not value.startswith("/v1/") or ".." in value:
            raise ValueError("api_prefix")
        return value

    @field_validator("config_schema")
    @classmethod
    def _schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            jsonschema.Draft202012Validator.check_schema(value)
        except jsonschema.SchemaError as exc:
            raise ValueError("config_schema") from exc
        return value


class ModuleRegistry:
    def __init__(self, manifests: dict[str, ModuleManifest]) -> None:
        self._manifests = dict(manifests)

    @classmethod
    def load(cls, root: Path) -> ModuleRegistry:
        """Valida todos os ``root/*/manifest.json``; um manifesto inválido falha o arranque."""
        manifests: dict[str, ModuleManifest] = {}
        for path in sorted(root.glob("*/manifest.json")):
            try:
                manifest = ModuleManifest.model_validate(json.loads(path.read_text("utf-8")))
            except (ValidationError, ValueError) as exc:
                raise ValidationFailed(subcode="invalid_module_manifest") from exc
            if manifest.name != path.parent.name or manifest.name in manifests:
                raise ValidationFailed(subcode="module_name_mismatch")
            manifests[manifest.name] = manifest
        return cls(manifests)

    @property
    def names(self) -> list[str]:
        return sorted(self._manifests)

    def get(self, name: str) -> ModuleManifest:
        try:
            return self._manifests[name]
        except KeyError:
            raise ValidationFailed(subcode="unknown_module") from None

    def validate_config(self, name: str, config: dict[str, Any]) -> dict[str, Any]:
        """Valida ``config`` contra o ``config_schema`` do módulo (422 se inválido)."""
        validator = jsonschema.Draft202012Validator(self.get(name).config_schema)
        if next(validator.iter_errors(config), None) is not None:
            raise ValidationFailed(subcode="invalid_feature_config")
        return config
