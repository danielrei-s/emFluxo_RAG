"""Manifest de um corpus (``manifest.yaml``): utilizadores, grupos e ACL por documento.

Usado pela CLI e pelos testes. Os IDs de tenant, utilizador e documento são UUIDs estáveis
(``uuid5``) derivados dos nomes, para que a ingestão e as perguntas concordem entre si.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import yaml

from rag_core.types import Acl, Classification, Principal, Role, SourceFile

_NAMESPACE = uuid.UUID("5d0c1f6e-0a54-4b4e-9f0d-3a2f6a7c1e11")
DEFAULT_TENANT = "dev"
DEFAULT_USER = "dev"


def stable_id(*parts: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, "/".join(parts)))


class CorpusManifest:
    """Leitura do manifest; sem ficheiro, só existe o tenant ``dev`` com um owner."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data: dict[str, Any] = data or {"tenants": {}, "documents": [], "invalid": []}

    @classmethod
    def load(cls, path: Path) -> CorpusManifest:
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")))

    # ------------------------------------------------------------------ identidades

    def tenant_id(self, slug: str) -> str:
        if slug != DEFAULT_TENANT and slug not in self.data["tenants"]:
            raise KeyError(slug)
        return stable_id("tenant", slug)

    def workspace_id(self, tenant: str, workspace: str = "default") -> str:
        return (
            stable_id("workspace", tenant)
            if workspace == "default"
            else stable_id("workspace", tenant, workspace)
        )

    def doc_uuid(self, manifest_id: str) -> str:
        return stable_id("doc", manifest_id)

    def principal_for(self, tenant: str, user: str) -> Principal:
        """``Principal`` do manifest; no tenant ``dev`` sem manifest, o owner ``dev``."""
        users = self.data["tenants"].get(tenant, {}).get("users", [])
        for entry in users:
            if entry["id"] == user:
                return Principal(
                    tenant_id=self.tenant_id(tenant),
                    user_id=stable_id("user", tenant, user),
                    role=Role(entry["role"]),
                    groups=frozenset(entry["groups"]),
                )
        if tenant == DEFAULT_TENANT and not users:
            return Principal(
                tenant_id=self.tenant_id(tenant),
                user_id=stable_id("user", tenant, user),
                role=Role.OWNER,
            )
        raise KeyError(f"{tenant}/{user}")

    # ------------------------------------------------------------------ documentos

    def entry_by_id(self, manifest_id: str) -> dict[str, Any]:
        for doc in self.data["documents"]:
            if doc["id"] == manifest_id:
                entry: dict[str, Any] = doc
                return entry
        raise KeyError(manifest_id)

    def entry_by_filename(self, tenant: str, filename: str) -> dict[str, Any] | None:
        for doc in self.data["documents"]:
            if doc["tenant"] == tenant and Path(doc["file"]).name == filename:
                entry: dict[str, Any] = doc
                return entry
        return None

    def _source(
        self,
        tenant: str,
        workspace: str,
        doc_id: str,
        filename: str,
        uri: str,
        entry: dict[str, Any] | None,
    ) -> SourceFile:
        acl: dict[str, Any] = (
            entry["acl"] if entry else {"all_members": True, "groups": [], "users": []}
        )
        return SourceFile(
            tenant_id=self.tenant_id(tenant),
            workspace_id=self.workspace_id(tenant, workspace),
            doc_id=doc_id,
            source_uri=uri,
            filename=filename,
            acl=Acl(
                all_members=acl["all_members"],
                users=frozenset(acl["users"]),
                groups=frozenset(acl["groups"]),
            ),
            classification=Classification(entry["classification"] if entry else "internal"),
        )

    def source_for_id(self, manifest_id: str) -> SourceFile:
        """``SourceFile`` central de um documento do manifest (URI ``upload://``)."""
        entry = self.entry_by_id(manifest_id)
        doc_id = self.doc_uuid(manifest_id)
        filename = Path(entry["file"]).name
        return self._source(
            entry["tenant"], "default", doc_id, filename, f"upload://{doc_id}/{filename}", entry
        )

    def source_for_file(
        self, tenant: str, workspace: str, rel_path: str, filename: str
    ) -> SourceFile:
        """Fonte de um ficheiro de pasta: ACL do manifest se o conhecer, senão ``all_members``."""
        entry = self.entry_by_filename(tenant, filename)
        doc_id = (
            self.doc_uuid(entry["id"])
            if entry
            else stable_id("file", tenant, workspace, rel_path.replace("\\", "/"))
        )
        return self._source(
            tenant, workspace, doc_id, filename, f"file://{rel_path.replace(chr(92), '/')}", entry
        )
