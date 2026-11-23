"""Estado partilhado do motor local: repositório, FileGate e índice (F11-T05)."""

from __future__ import annotations

from dataclasses import dataclass

from rag_core.interfaces import VectorStore

from rag_local.filegate import FileGate
from rag_local.repo import LocalRepo

LOCAL_TENANT = "local"  # o índice local tem um único "tenant"
SUPPORTED_EXTENSIONS = frozenset(
    {".txt", ".md", ".csv", ".html", ".htm", ".docx", ".xlsx", ".pptx", ".pdf", ".eml"}
)


@dataclass
class LocalState:
    repo: LocalRepo
    gate: FileGate
    store: VectorStore
