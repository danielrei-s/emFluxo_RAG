"""Erros do gateway: reutiliza os do core e o formato problem+json partilhado."""

from __future__ import annotations

from rag_core.errors import (
    AccessDenied,
    QuotaExceeded,
    RagError,
    RateLimited,
    UpstreamError,
    ValidationFailed,
)
from rag_core.web import problem_response

__all__ = [
    "AccessDenied",
    "QuotaExceeded",
    "RagError",
    "RateLimited",
    "UpstreamError",
    "ValidationFailed",
    "problem_response",
]
