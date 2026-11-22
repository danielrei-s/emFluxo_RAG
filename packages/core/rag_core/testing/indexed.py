"""Corpus sintético indexado com fakes e parsers no próprio processo (só para testes)."""

from __future__ import annotations

from typing import Any

from rag_core.clock import FakeClock
from rag_core.config import Settings
from rag_core.fakes import FakeEmbedder, InMemoryVectorStore
from rag_core.ingestion.pipeline import IngestionService
from rag_core.parsing.lite import lite_registry
from rag_core.testing import corpus
from rag_core.types import StructuredDocument


def inproc_runner(data: bytes, **kwargs: Any) -> StructuredDocument:
    """Parseia no próprio processo (rápido); a ingestão real passa sempre pelo sandbox."""
    detected = kwargs["detected"]
    parser = lite_registry().get(detected)
    return parser.parse(
        data, filename=kwargs["filename"], detected=detected, limits=kwargs["limits"]
    )


def build_indexed_store(*doc_ids: str) -> InMemoryVectorStore:
    """Indexa os documentos pedidos (por omissão, todos os do manifest, válidos)."""
    store = InMemoryVectorStore()
    service = IngestionService(
        embedder=FakeEmbedder(),
        store=store,
        settings=Settings.for_tests(),
        clock=FakeClock(),
        runner=inproc_runner,
    )
    ids = doc_ids or tuple(d["id"] for d in corpus.load_manifest()["documents"])
    for doc_id in ids:
        service.ingest_file(corpus.source_file_for(doc_id), corpus.read_bytes(doc_id))
    return store
