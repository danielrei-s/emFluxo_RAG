"""Acesso ao corpus sintético (``fixtures/corpus``) para testes: manifest, principais e fontes."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from rag_core.manifest import CorpusManifest, stable_id
from rag_core.types import Acl, Principal, SourceFile

CORPUS_DIR = Path(__file__).resolve().parents[4] / "fixtures" / "corpus"


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    """Devolve o ``manifest.yaml`` do corpus (não alterar o resultado)."""
    manifest: dict[str, Any] = yaml.safe_load((CORPUS_DIR / "manifest.yaml").read_text("utf-8"))
    return manifest


def _manifest() -> CorpusManifest:
    return CorpusManifest(load_manifest())


def _stable_id(*parts: str) -> str:
    return stable_id(*parts)


def tenant_id(slug: str) -> str:
    """ID estável do tenant a partir do slug (``aurora``, ``boreal``)."""
    return _manifest().tenant_id(slug)


def doc_uuid(manifest_id: str) -> str:
    """ID central estável (UUID) de um documento do manifest (ex.: ``A01``)."""
    return _manifest().doc_uuid(manifest_id)


def principal_for(tenant: str, user: str) -> Principal:
    """``Principal`` de um utilizador do manifest (role e grupos incluídos)."""
    return _manifest().principal_for(tenant, user)


def _entry(manifest_id: str) -> dict[str, Any]:
    for doc in load_manifest()["documents"]:
        if doc["id"] == manifest_id:
            entry: dict[str, Any] = doc
            return entry
    raise KeyError(manifest_id)


def source_file_for(manifest_id: str) -> SourceFile:
    """``SourceFile`` central de um documento, com a ACL e classificação do manifest."""
    return _manifest().source_for_id(manifest_id)


def read_bytes(manifest_id: str) -> bytes:
    """Conteúdo do ficheiro de um documento do manifest."""
    path = CORPUS_DIR / str(_entry(manifest_id)["file"])
    return path.read_bytes()


def all_canaries() -> frozenset[str]:
    """Todos os canários do manifest (nunca podem aparecer em respostas nem logs)."""
    return frozenset(c for doc in load_manifest()["documents"] for c in doc["canaries"])


def invalid_files() -> list[str]:
    """Nomes dos ficheiros inválidos do corpus (``fixtures/corpus/invalid``)."""
    return [Path(e["file"]).name for e in load_manifest()["invalid"]]


def read_invalid(filename: str) -> bytes:
    """Conteúdo de um ficheiro inválido do corpus."""
    return (CORPUS_DIR / "invalid" / filename).read_bytes()


def invalid_source(filename: str) -> SourceFile:
    """``SourceFile`` (tenant Aurora, visível a todos) para um ficheiro inválido."""
    if filename not in invalid_files():
        raise KeyError(filename)
    doc_id = doc_uuid(f"invalid/{filename}")
    return SourceFile(
        tenant_id=tenant_id("aurora"),
        workspace_id=_stable_id("workspace", "aurora"),
        doc_id=doc_id,
        source_uri=f"upload://{doc_id}/{filename}",
        filename=filename,
        acl=Acl(all_members=True),
    )
