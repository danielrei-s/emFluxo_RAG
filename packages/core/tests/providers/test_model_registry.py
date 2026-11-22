"""Testes de F5-T02: registo de modelos (INV-21 licenças, INV-22 revisão e hash)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from rag_core.errors import ValidationFailed
from rag_core.ids import sha256_hex
from rag_core.providers import ModelRegistry, ModelSpec

ROOT = Path(__file__).resolve().parents[4]


def _spec(**overrides: Any) -> ModelSpec:
    base: dict[str, Any] = {
        "kind": "llm",
        "backend": "openai_compat",
        "model": "m",
        "license": "Apache-2.0",
    }
    return ModelSpec.model_validate({**base, **overrides})


def _write(tmp_path: Path, models: dict[str, Any]) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump({"models": models}), encoding="utf-8")
    return path


def test_example_file_loads_and_exposes_aliases() -> None:
    registry = ModelRegistry.from_file(ROOT / "models.example.yaml")
    assert registry.aliases == ["rag-default", "rag-embed"]
    llm = registry.get("rag-default")
    assert (llm.kind, llm.base_url_env, llm.external) == ("llm", "RAG_OLLAMA_URL", False)
    assert registry.get("rag-embed").dim == 1024
    with pytest.raises(ValidationFailed) as exc:
        registry.get("nao-existe")
    assert exc.value.subcode == "unknown_model_alias"


@pytest.mark.parametrize(
    "license_id", ["Apache-2.0", "MIT", "BSD-3-Clause", "bsd-2-clause", " mit "]
)
def test_allowed_licenses_pass(license_id: str) -> None:
    assert _spec(license=license_id).license == license_id


@pytest.mark.parametrize(
    "license_id", ["CC-BY-NC-4.0", "research-only", "Proprietary", "AGPL-3.0", "unknown"]
)
def test_inv21_registry_rejects_noncommercial_model_license(license_id: str) -> None:
    with pytest.raises(ValidationFailed) as exc:
        _spec(license=license_id)
    assert exc.value.subcode == "model_license_forbidden"


def test_restricted_licenses_need_an_adr() -> None:
    for license_id in ("Llama-3-Community", "Gemma"):
        with pytest.raises(ValidationFailed) as exc:
            _spec(license=license_id)
        assert exc.value.subcode == "model_license_needs_adr"
        assert _spec(license=license_id, adr="0009").adr == "0009"


def test_inv22_registry_requires_revision_and_verifies_hash(tmp_path: Path) -> None:
    content = b"pesos do modelo"
    files = [{"name": "model.onnx", "sha256": sha256_hex(content)}]
    with pytest.raises(ValidationFailed) as exc:  # ficheiros descarregados sem revisão fixada
        _spec(kind="embedding", dim=4, files=files)
    assert exc.value.subcode == "model_revision_missing"

    path = _write(
        tmp_path,
        {"emb": {"kind": "embedding", "backend": "fastembed", "model": "m", "license": "MIT",
                 "dim": 4, "revision": "abc123", "files": files}},
    )  # fmt: skip
    registry = ModelRegistry.from_file(path)
    base = tmp_path / "cache"
    base.mkdir()
    with pytest.raises(ValidationFailed) as missing:
        registry.verify_files("emb", base)
    assert missing.value.subcode == "model_file_missing"

    (base / "model.onnx").write_bytes(b"adulterado")
    with pytest.raises(ValidationFailed) as mismatch:
        registry.verify_files("emb", base)
    assert mismatch.value.subcode == "model_hash_mismatch"

    (base / "model.onnx").write_bytes(content)
    assert registry.verify_files("emb", base) == [base / "model.onnx"]


def test_models_without_files_verify_trivially_and_validation_details(tmp_path: Path) -> None:
    registry = ModelRegistry({"llm": _spec()})
    assert registry.verify_files("llm", tmp_path) == []
    with pytest.raises(ValueError):  # sha256 mal formado
        _spec(revision="r", files=[{"name": "f", "sha256": "ABC"}])
    with pytest.raises(ValueError):  # embeddings precisam de dim
        _spec(kind="embedding")
    assert _spec(kind="embedding", dim=8, query_prefix="query: ", document_prefix="passage: ")
    assert ModelRegistry.from_file(_write(tmp_path, {})).aliases == []
