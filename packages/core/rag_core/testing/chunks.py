"""Fábrica de chunks para testes (``make_chunk``)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rag_core.fakes.embedder import FakeEmbedder
from rag_core.ids import chunk_id as make_chunk_id
from rag_core.ids import sha256_hex
from rag_core.interfaces import Embedder
from rag_core.types import Acl, Chunk, ChunkMetadata, Classification, Origin

_DEFAULT_EMBEDDER = FakeEmbedder()


def make_chunk(
    text: str,
    *,
    doc_id: str = "d1",
    ordinal: int = 0,
    tenant_id: str = "t1",
    workspace_id: str = "w1",
    classification: Classification = Classification.INTERNAL,
    acl: Acl | None = None,
    origin: Origin = Origin.CENTRAL,
    local_only: bool = False,
    embed: bool = True,
    embedder: Embedder | None = None,
    **metadata_overrides: Any,
) -> Chunk:
    """Cria um ``Chunk`` válido e determinístico.

    ``chunk_id`` vem de ``ids.chunk_id``; ``doc_hash`` depende só de ``doc_id``; a ACL por omissão
    é ``all_members``. Com ``embed=True`` o embedding é calculado com ``embedder`` (por omissão
    um ``FakeEmbedder``). ``metadata_overrides`` substitui qualquer campo de ``ChunkMetadata``.
    """
    used = embedder or _DEFAULT_EMBEDDER
    content_hash = sha256_hex(text)
    fields: dict[str, Any] = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "doc_id": doc_id,
        "source_uri": f"upload://{doc_id}/f.txt",
        "content_hash": content_hash,
        "doc_hash": sha256_hex(f"file-{doc_id}"),
        "acl": acl if acl is not None else Acl(all_members=True),
        "classification": classification,
        "ingested_at": datetime(2026, 1, 1, tzinfo=UTC),
        "parser_version": "1",
        "origin": origin,
        "local_only": local_only,
    }
    fields.update(metadata_overrides)
    return Chunk(
        chunk_id=make_chunk_id(doc_id, ordinal, content_hash),
        ordinal=ordinal,
        text=text,
        metadata=ChunkMetadata(**fields),
        embedding=tuple(used.embed_documents([text])[0]) if embed else None,
        embedding_model=used.model_id if embed else None,
    )
