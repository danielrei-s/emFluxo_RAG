"""Montagem de ``Chunk`` a partir de ``ChunkDraft`` (F3-T12): ids, hashes, idioma e flags."""

from __future__ import annotations

from collections.abc import Sequence

from langdetect import DetectorFactory
from langdetect import detect as _langdetect
from langdetect.lang_detect_exception import LangDetectException

from rag_core.ids import chunk_id, sha256_hex
from rag_core.ingestion.chunking import ChunkDraft
from rag_core.ingestion.sanitize import detect_injection
from rag_core.interfaces import Clock
from rag_core.types import Chunk, ChunkMetadata, SourceFile, StructuredDocument

INJECTION_FLAG = "suspected_injection"
LANGUAGE_SAMPLE_CHARS = 2000
MIN_LANGUAGE_CHARS = 50

DetectorFactory.seed = 0  # deteção determinística


def detect_language(doc: StructuredDocument) -> str | None:
    """Idioma (ex.: ``pt``) pelos primeiros 2000 caracteres; ``None`` se houver pouco texto."""
    text = " ".join(b.text for b in doc.blocks)[:LANGUAGE_SAMPLE_CHARS]
    if len(text.strip()) < MIN_LANGUAGE_CHARS:
        return None
    try:
        return str(_langdetect(text))
    except LangDetectException:  # texto sem características linguísticas (números, símbolos)
        return None


def build_chunks(
    source: SourceFile,
    doc: StructuredDocument,
    drafts: Sequence[ChunkDraft],
    *,
    doc_hash: str,
    clock: Clock,
) -> list[Chunk]:
    """Transforma os rascunhos em chunks com metadados completos (INV-01/02 incluídos)."""
    language = detect_language(doc)
    ingested_at = clock.now()
    chunks: list[Chunk] = []
    for draft in drafts:
        content_hash = sha256_hex(draft.text)
        flags = set(draft.flags)
        if detect_injection(draft.text):
            flags.add(INJECTION_FLAG)
        metadata = ChunkMetadata(
            tenant_id=source.tenant_id,
            workspace_id=source.workspace_id,
            doc_id=source.doc_id,
            source_uri=source.source_uri,
            title=doc.title,
            heading_path=draft.heading_path,
            page_start=draft.page_start,
            page_end=draft.page_end,
            content_hash=content_hash,
            doc_hash=doc_hash,
            acl=source.acl,
            classification=source.classification,
            language=language,
            ingested_at=ingested_at,
            parser_version=doc.parser_version,
            origin=source.origin,
            local_only=source.local_only,
            flags=frozenset(flags),
        )
        chunks.append(
            Chunk(
                chunk_id=chunk_id(source.doc_id, draft.ordinal, content_hash),
                ordinal=draft.ordinal,
                text=draft.text,
                metadata=metadata,
            )
        )
    return chunks
