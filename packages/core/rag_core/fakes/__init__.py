"""Fakes oficiais (C10): rápidos, determinísticos e sem rede."""

from rag_core.clock import FakeClock
from rag_core.fakes.blobstore import InMemoryBlobStore
from rag_core.fakes.embedder import FakeEmbedder
from rag_core.fakes.llm import FakeLLMProvider
from rag_core.fakes.reranker import FakeReranker
from rag_core.fakes.vectorstore import InMemoryVectorStore
from rag_core.tokens import ApproxTokenCounter

__all__ = [
    "ApproxTokenCounter",
    "FakeClock",
    "FakeEmbedder",
    "FakeLLMProvider",
    "FakeReranker",
    "InMemoryBlobStore",
    "InMemoryVectorStore",
]
