"""A suite de contrato do VectorStore aplicada ao ``InMemoryVectorStore``."""

from __future__ import annotations

from collections.abc import Sequence

from rag_core.errors import ValidationFailed
from rag_core.fakes import InMemoryVectorStore
from rag_core.interfaces import VectorStore
from rag_core.types import Chunk, Origin

from ..contract.vectorstore_contract import VectorStoreContract


class TestInMemoryVectorStoreContract(VectorStoreContract):
    supports_local_origin = True

    def make_store(self) -> VectorStore:
        return InMemoryVectorStore()


class _CentralOnlyStore(InMemoryVectorStore):
    """Como o futuro ``PgVectorStore``: recusa chunks com ``origin=local`` (INV-04)."""

    def upsert(self, chunks: Sequence[Chunk]) -> None:
        if any(c.metadata.origin == Origin.LOCAL for c in chunks):
            raise ValidationFailed(subcode="local_origin_not_allowed")
        super().upsert(chunks)


class TestCentralOnlyStoreContract(VectorStoreContract):
    """Exercita o ramo ``supports_local_origin = False`` da suite."""

    supports_local_origin = False

    def make_store(self) -> VectorStore:
        return _CentralOnlyStore()
