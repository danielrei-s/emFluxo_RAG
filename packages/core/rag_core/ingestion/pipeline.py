"""Serviço de ingestão incremental (F3-T13): ficheiros → chunks com embeddings no índice.

Todo o parsing passa pelo sandbox (``run_parser_sandboxed``). Erros num ficheiro nunca param o
lote: ficam no ``IngestResult``. Os logs só têm ``doc_id``, ``hash``, ``count``, ``duration_ms``
e ``error_code`` (INV-03).

Limitação conhecida: os anexos (documentos filhos) são rastreados em memória, porque o contrato
``VectorStore`` não guarda o pai. Com o ``PgVectorStore`` (F7) o ``parent_doc_id`` passa a ser
uma coluna e esta memória deixa de ser precisa.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from rag_core.clock import SystemClock
from rag_core.config import Settings
from rag_core.errors import RagError, ValidationFailed
from rag_core.ids import child_doc_id, sha256_hex
from rag_core.ingestion.chunking import chunk_document, embedding_text
from rag_core.ingestion.detect import sniff
from rag_core.ingestion.metadata import build_chunks
from rag_core.ingestion.sandbox import run_parser_sandboxed
from rag_core.interfaces import Clock, Embedder, ParseLimits, TokenCounter, VectorStore
from rag_core.logging import get_logger
from rag_core.tokens import ApproxTokenCounter
from rag_core.types import RawAttachment, SourceFile, StructuredDocument

EMBED_BATCH_SIZE = 32
MAX_ATTACHMENT_DEPTH = 2
Status = Literal["indexed", "unchanged", "failed", "deleted"]
Runner = Callable[..., StructuredDocument]


def _log() -> Any:
    """Logger criado no momento do uso: respeita a configuração de logging atual."""
    return get_logger("ingestion")


@dataclass(frozen=True)
class IngestResult:
    doc_id: str
    status: Status
    error_code: str | None = None
    chunk_count: int = 0
    warnings: tuple[str, ...] = ()


def _error_code(error: RagError) -> str:
    if isinstance(error, ValidationFailed) and error.subcode:
        return f"{error.code}:{error.subcode}"
    return error.code


def _child_source(parent: SourceFile, attachment: RawAttachment) -> SourceFile:
    doc_id = child_doc_id(parent.doc_id, attachment.filename)
    if parent.source_uri.startswith("upload://"):
        source_uri = f"upload://{doc_id}/{attachment.filename}"
    else:
        source_uri = f"{parent.source_uri}#{attachment.filename}"
    return parent.model_copy(
        update={
            "doc_id": doc_id,
            "source_uri": source_uri,
            "filename": attachment.filename,
            "parent_doc_id": parent.doc_id,
        }
    )


class IngestionService:
    """Orquestra sniff → sandbox → chunking → embeddings → índice, de forma incremental."""

    def __init__(
        self,
        *,
        registry_profile: Literal["lite", "full"] = "lite",
        embedder: Embedder,
        store: VectorStore,
        settings: Settings,
        clock: Clock | None = None,
        limits: ParseLimits | None = None,
        counter: TokenCounter | None = None,
        runner: Runner = run_parser_sandboxed,
        artifacts_path: Path | None = None,
    ) -> None:
        self._profile = registry_profile
        self._embedder = embedder
        self._store = store
        self._settings = settings
        self._clock = clock or SystemClock()
        self._limits = limits or ParseLimits()
        self._counter = counter or ApproxTokenCounter()
        self._runner = runner
        self._artifacts_path = artifacts_path
        self._children: dict[tuple[str, str], set[str]] = {}

    # ------------------------------------------------------------------ ingestão

    def ingest_file(self, source: SourceFile, data: bytes) -> list[IngestResult]:
        """Ingere um ficheiro e os seus anexos. Devolve um resultado por documento."""
        hashes = self._store.document_hashes(source.tenant_id, source.workspace_id)
        return self._ingest(source, data, hashes, depth=0)

    def _ingest(
        self, source: SourceFile, data: bytes, hashes: Mapping[str, str], *, depth: int
    ) -> list[IngestResult]:
        started = time.perf_counter()
        doc_hash = sha256_hex(data)
        if hashes.get(source.doc_id) == doc_hash:
            _log().info("ingestion.unchanged", doc_id=source.doc_id, hash=doc_hash)
            return [IngestResult(source.doc_id, "unchanged")]
        try:
            result, attachments = self._index(source, data, doc_hash)
        except RagError as error:
            code = _error_code(error)
            _log().warning("ingestion.failed", doc_id=source.doc_id, hash=doc_hash, error_code=code)
            return [IngestResult(source.doc_id, "failed", error_code=code)]
        _log().info(
            "ingestion.indexed",
            doc_id=source.doc_id,
            hash=doc_hash,
            count=result.chunk_count,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        results = [result]
        key = (source.tenant_id, source.doc_id)
        current: set[str] = set()
        if depth < MAX_ATTACHMENT_DEPTH:
            for attachment in attachments:
                child = _child_source(source, attachment)
                current.add(child.doc_id)
                results.extend(self._ingest(child, attachment.data, hashes, depth=depth + 1))
        for stale in sorted(self._children.get(key, set()) - current):  # anexo que já não existe
            self.delete(source.tenant_id, stale)
        if current:
            self._children[key] = current
        else:
            self._children.pop(key, None)
        return results

    def _index(
        self, source: SourceFile, data: bytes, doc_hash: str
    ) -> tuple[IngestResult, tuple[RawAttachment, ...]]:
        detected, warnings = sniff(data, source.filename, self._limits)
        doc = self._runner(
            data,
            filename=source.filename,
            detected=detected,
            profile=self._profile,
            limits=self._limits,
            artifacts_path=self._artifacts_path,
        )
        drafts = chunk_document(doc, settings=self._settings.chunking, counter=self._counter)
        if not drafts:
            raise ValidationFailed(subcode="no_text_extracted")
        chunks = build_chunks(source, doc, drafts, doc_hash=doc_hash, clock=self._clock)
        texts = [embedding_text(d) for d in drafts]
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH_SIZE):
            vectors.extend(self._embedder.embed_documents(texts[start : start + EMBED_BATCH_SIZE]))
        embedded = [
            c.model_copy(update={"embedding": tuple(v), "embedding_model": self._embedder.model_id})
            for c, v in zip(chunks, vectors, strict=True)
        ]
        self._store.delete_document(source.tenant_id, source.doc_id)  # versão anterior
        self._store.upsert(embedded)
        all_warnings = tuple(dict.fromkeys([*warnings, *doc.warnings]))
        return IngestResult(
            source.doc_id, "indexed", chunk_count=len(chunks), warnings=all_warnings
        ), doc.attachments

    # ---------------------------------------------------------------- eliminação

    def delete(self, tenant_id: str, doc_id: str) -> list[IngestResult]:
        """Apaga o documento e os seus anexos do índice (INV-18)."""
        results: list[IngestResult] = []
        for child_id in sorted(self._children.pop((tenant_id, doc_id), set())):
            results.extend(self.delete(tenant_id, child_id))
        count = self._store.delete_document(tenant_id, doc_id)
        _log().info("ingestion.deleted", doc_id=doc_id, count=count)
        return [IngestResult(doc_id, "deleted", chunk_count=count), *results]

    # ------------------------------------------------------------- sincronização

    def sync_workspace(
        self,
        tenant_id: str,
        workspace_id: str,
        entries: Mapping[str, tuple[SourceFile, Callable[[], bytes], str]],
    ) -> list[IngestResult]:
        """Alinha o índice com ``entries`` (chave → (fonte, leitor de bytes, hash do ficheiro)).

        Só lê os bytes do que mudou; apaga o que já não existe (INV-18).
        """
        stored = dict(self._store.document_hashes(tenant_id, workspace_id))
        results: list[IngestResult] = []
        wanted: set[str] = set()
        for source, read, doc_hash in entries.values():
            wanted.add(source.doc_id)
            if stored.get(source.doc_id) == doc_hash:
                results.append(IngestResult(source.doc_id, "unchanged"))
                continue
            try:
                data = read()
            except OSError:
                _log().warning("ingestion.failed", doc_id=source.doc_id, error_code="read_failed")
                results.append(IngestResult(source.doc_id, "failed", error_code="read_failed"))
                continue
            results.extend(self._ingest(source, data, stored, depth=0))
        known_children = {
            c for (t, _), ids in self._children.items() if t == tenant_id for c in ids
        }
        for doc_id in sorted(set(stored) - wanted - known_children):
            results.extend(self.delete(tenant_id, doc_id))
        return results
