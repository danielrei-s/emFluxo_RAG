"""Embedder falso, determinístico entre processos (usa ``hashlib``, nunca o hash embutido)."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from rag_core.text import normalize_tokens


class FakeEmbedder:
    """Hashing trick: cada token soma ±1 numa posição derivada do seu SHA-256."""

    def __init__(self, dim: int = 256) -> None:
        if dim < 1:
            raise ValueError("dim tem de ser positivo")
        self.dim = dim
        self.model_id = f"fake-hash-{dim}"

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in normalize_tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            vector[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:  # texto sem tokens, ou tokens que se anulam: vetor unitário fixo
            vector[0] = 1.0
            return vector
        return [v / norm for v in vector]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)
