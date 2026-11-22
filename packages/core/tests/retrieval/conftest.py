"""Corpus indexado (fakes, parsers no próprio processo) partilhado pelos testes de recuperação."""

from __future__ import annotations

from typing import Any

import pytest
from rag_core.clock import FakeClock
from rag_core.config import Settings
from rag_core.fakes import FakeEmbedder, InMemoryVectorStore
from rag_core.ingestion.pipeline import IngestionService
from rag_core.parsing.lite import lite_registry
from rag_core.testing import corpus
from rag_core.types import StructuredDocument


def inproc_runner(data: bytes, **kwargs: Any) -> StructuredDocument:
    detected = kwargs["detected"]
    return (
        lite_registry()
        .get(detected)
        .parse(data, filename=kwargs["filename"], detected=detected, limits=kwargs["limits"])
    )


@pytest.fixture(scope="session")
def indexed_store() -> InMemoryVectorStore:
    store = InMemoryVectorStore()
    service = IngestionService(
        embedder=FakeEmbedder(),
        store=store,
        settings=Settings.for_tests(),
        clock=FakeClock(),
        runner=inproc_runner,
    )
    for doc in corpus.load_manifest()["documents"]:
        service.ingest_file(corpus.source_file_for(doc["id"]), corpus.read_bytes(doc["id"]))
    return store
