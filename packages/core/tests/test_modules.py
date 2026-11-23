"""Testes de F9-T02: manifestos de módulos e validação da configuração (INV-19, INV-20)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from rag_core.errors import ValidationFailed
from rag_core.modules import ModuleRegistry

MODULES = Path(__file__).resolve().parents[3] / "modules"


def _manifest(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "demo-modulo",
        "version": "1.2.3",
        "description": "Demo",
        "ui_routes": ["/modules/demo"],
        "api_prefix": "/v1/modules/demo",
        "permissions": [],
        "config_schema": {"type": "object", "properties": {"n": {"type": "integer"}}},
        "default_enabled": False,
    }
    return {**base, **overrides}


def _write(root: Path, manifest: dict[str, Any], folder: str | None = None) -> None:
    directory = root / (folder or manifest.get("name", "x"))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_example_module_loads() -> None:
    registry = ModuleRegistry.load(MODULES)
    assert "example" in registry.names
    example = registry.get("example")
    assert example.default_enabled is False and example.api_prefix == "/v1/modules/example"


def test_manifest_validation_errors(tmp_path: Path) -> None:
    bad = (
        {"name": "Maiusculas"},
        {"name": "com_underscore"},
        {"version": "1.2"},
        {"api_prefix": "/outro/prefixo"},
        {"api_prefix": "/v1/../admin"},
        {"config_schema": {"type": "banana"}},
        {"description": ""},
        {"extra_field": 1},
    )
    for overrides in bad:
        root = tmp_path / str(abs(hash(json.dumps(overrides, sort_keys=True))))
        _write(root, _manifest(**overrides), folder="demo-modulo")
        with pytest.raises(ValidationFailed) as exc:
            ModuleRegistry.load(root)
        assert exc.value.subcode == "invalid_module_manifest", overrides
    mismatch = tmp_path / "mismatch"
    _write(mismatch, _manifest(), folder="outra-pasta")
    with pytest.raises(ValidationFailed) as name_exc:
        ModuleRegistry.load(mismatch)
    assert name_exc.value.subcode == "module_name_mismatch"
    broken = tmp_path / "broken"
    (broken / "x").mkdir(parents=True)
    (broken / "x" / "manifest.json").write_text("{não é json", encoding="utf-8")
    with pytest.raises(ValidationFailed):
        ModuleRegistry.load(broken)


def test_config_validation_against_the_schema() -> None:
    registry = ModuleRegistry.load(MODULES)
    assert registry.validate_config("example", {"greeting": "olá", "max_items": 5})
    for config in ({"greeting": 3}, {"max_items": 0}, {"extra": 1}, {"max_items": 101}):
        with pytest.raises(ValidationFailed) as exc:
            registry.validate_config("example", config)
        assert exc.value.subcode == "invalid_feature_config"
    with pytest.raises(ValidationFailed) as unknown:
        registry.get("nao-existe")
    assert unknown.value.subcode == "unknown_module"
