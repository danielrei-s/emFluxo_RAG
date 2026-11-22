"""Fixtures da geração: o corpus indexado com fakes é construído uma só vez por sessão."""

from __future__ import annotations

import pytest
from rag_core.fakes import InMemoryVectorStore
from rag_core.testing.indexed import build_indexed_store


@pytest.fixture(scope="session")
def indexed_store() -> InMemoryVectorStore:
    return build_indexed_store()
