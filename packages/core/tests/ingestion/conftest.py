"""Fixtures da ingestão: o corpus completo é ingerido uma só vez por sessão (via sandbox real)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest
from rag_core.clock import FakeClock
from rag_core.config import Settings
from rag_core.fakes import FakeEmbedder, InMemoryVectorStore
from rag_core.ingestion.pipeline import IngestionService, IngestResult
from rag_core.testing import corpus
from rag_core.types import Chunk


class RecordingStore(InMemoryVectorStore):
    """Guarda tudo o que foi indexado, para os testes inspecionarem os chunks."""

    def __init__(self) -> None:
        super().__init__()
        self.upserted: list[Chunk] = []

    def upsert(self, chunks: Sequence[Chunk]) -> None:
        self.upserted.extend(chunks)
        super().upsert(chunks)


@dataclass
class IngestedCorpus:
    store: RecordingStore
    results: dict[str, list[IngestResult]] = field(default_factory=dict)


@pytest.fixture(scope="session")
def ingested_corpus() -> IngestedCorpus:
    store = RecordingStore()
    service = IngestionService(
        embedder=FakeEmbedder(),
        store=store,
        settings=Settings.for_tests(),
        clock=FakeClock(),
    )
    ingested = IngestedCorpus(store=store)
    for doc in corpus.load_manifest()["documents"]:
        doc_id = doc["id"]
        ingested.results[doc_id] = service.ingest_file(
            corpus.source_file_for(doc_id), corpus.read_bytes(doc_id)
        )
    for name in corpus.invalid_files():
        ingested.results[f"invalid/{name}"] = service.ingest_file(
            corpus.invalid_source(name), corpus.read_invalid(name)
        )
    return ingested
