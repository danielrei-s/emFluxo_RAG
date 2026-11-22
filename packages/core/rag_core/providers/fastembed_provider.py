"""Embeddings ONNX locais com ``fastembed`` (F5-T02, extra ``onnx``). Sem downloads em runtime."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any


def _load_text_embedding(model_name: str, cache_dir: Path) -> Any:  # pragma: no cover - extra onnx
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=model_name, cache_dir=str(cache_dir), local_files_only=True)


def _normalize(vector: Sequence[float]) -> list[float]:
    values = [float(x) for x in vector]
    norm = math.sqrt(sum(x * x for x in values))
    return [x / norm for x in values] if norm > 0 else values


class FastEmbedEmbedder:
    """Modelo ONNX já descarregado em ``cache_dir`` (revisão e hash verificados no registo)."""

    def __init__(
        self,
        model_name: str,
        cache_dir: Path,
        query_prefix: str = "",
        document_prefix: str = "",
        dim: int | None = None,
        *,
        loader: Callable[[str, Path], Any] = _load_text_embedding,
    ) -> None:
        self.model_id = model_name
        self._model = loader(model_name, cache_dir)
        self._query_prefix = query_prefix
        self._document_prefix = document_prefix
        self.dim = dim if dim is not None else len(self.embed_query("dimensão"))

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        prefixed = [self._document_prefix + t for t in texts]
        return [_normalize(v) for v in self._model.embed(prefixed)]

    def embed_query(self, text: str) -> list[float]:
        return _normalize(next(iter(self._model.embed([self._query_prefix + text]))))
