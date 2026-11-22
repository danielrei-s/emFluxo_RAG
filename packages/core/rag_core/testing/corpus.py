"""Acesso ao corpus sintético (``fixtures/corpus``) para testes: manifest, principais e fontes."""

from __future__ import annotations

import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from rag_core.types import Acl, Classification, Principal, Role, SourceFile

CORPUS_DIR = Path(__file__).resolve().parents[4] / "fixtures" / "corpus"
_NAMESPACE = uuid.UUID("5d0c1f6e-0a54-4b4e-9f0d-3a2f6a7c1e11")


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    """Devolve o ``manifest.yaml`` do corpus (não alterar o resultado)."""
    manifest: dict[str, Any] = yaml.safe_load((CORPUS_DIR / "manifest.yaml").read_text("utf-8"))
    return manifest


def _stable_id(*parts: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, "/".join(parts)))


def tenant_id(slug: str) -> str:
    """ID estável do tenant a partir do slug (``aurora``, ``boreal``)."""
    if slug not in load_manifest()["tenants"]:
        raise KeyError(slug)
    return _stable_id("tenant", slug)


def doc_uuid(manifest_id: str) -> str:
    """ID central estável (UUID) de um documento do manifest (ex.: ``A01``)."""
    return _stable_id("doc", manifest_id)


def principal_for(tenant: str, user: str) -> Principal:
    """``Principal`` de um utilizador do manifest (role e grupos incluídos)."""
    for entry in load_manifest()["tenants"][tenant]["users"]:
        if entry["id"] == user:
            return Principal(
                tenant_id=tenant_id(tenant),
                user_id=_stable_id("user", tenant, user),
                role=Role(entry["role"]),
                groups=frozenset(entry["groups"]),
            )
    raise KeyError(f"{tenant}/{user}")


def _entry(manifest_id: str) -> dict[str, Any]:
    for doc in load_manifest()["documents"]:
        if doc["id"] == manifest_id:
            entry: dict[str, Any] = doc
            return entry
    raise KeyError(manifest_id)


def source_file_for(manifest_id: str) -> SourceFile:
    """``SourceFile`` central de um documento, com a ACL e classificação do manifest."""
    doc = _entry(manifest_id)
    acl = doc["acl"]
    doc_id = doc_uuid(manifest_id)
    filename = Path(doc["file"]).name
    return SourceFile(
        tenant_id=tenant_id(doc["tenant"]),
        workspace_id=_stable_id("workspace", doc["tenant"]),
        doc_id=doc_id,
        source_uri=f"upload://{doc_id}/{filename}",
        filename=filename,
        acl=Acl(
            all_members=acl["all_members"],
            users=frozenset(acl["users"]),
            groups=frozenset(acl["groups"]),
        ),
        classification=Classification(doc["classification"]),
    )


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
