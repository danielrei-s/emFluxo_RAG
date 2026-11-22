"""Reranker por cross-encoder (F5-T02): fastembed (ONNX) ou sentence-transformers (servidor)."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

from rag_core.types import SearchHit


def _load_fastembed(model_name: str, cache_dir: Path | None) -> Any:  # pragma: no cover - extra
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    kwargs: dict[str, Any] = {"model_name": model_name, "local_files_only": True}
    if cache_dir is not None:
        kwargs["cache_dir"] = str(cache_dir)
    return TextCrossEncoder(**kwargs)


def _load_sentence_transformers(
    model_name: str, cache_dir: Path | None
) -> Any:  # pragma: no cover - extra st
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name, cache_folder=None if cache_dir is None else str(cache_dir))


def sigmoid(x: float) -> float:
    """Sigmoide estável: converte o score bruto do modelo em 0-1."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


class CrossEncoderReranker:
    """Pontua cada par (pergunta, excerto) e ordena; scores normalizados para 0-1."""

    def __init__(
        self,
        model_name: str,
        backend: Literal["fastembed", "sentence_transformers"] = "fastembed",
        cache_dir: Path | None = None,
        *,
        loader: Callable[[str, Path | None], Any] | None = None,
    ) -> None:
        self.model_id = model_name
        self._backend = backend
        default = _load_fastembed if backend == "fastembed" else _load_sentence_transformers
        self._model = (loader or default)(model_name, cache_dir)

    def _scores(self, query: str, documents: list[str]) -> list[float]:
        if self._backend == "fastembed":
            return [float(s) for s in self._model.rerank(query, documents)]
        return [float(s) for s in self._model.predict([[query, d] for d in documents])]

    def rerank(self, query: str, hits: Sequence[SearchHit], *, top_n: int) -> list[SearchHit]:
        if not hits:
            return []
        scores = self._scores(query, [h.chunk.text for h in hits])
        scored = sorted(
            zip(scores, hits, strict=True), key=lambda item: (-item[0], item[1].chunk.chunk_id)
        )
        return [
            SearchHit(chunk=hit.chunk, score=sigmoid(score), stage="reranked")
            for score, hit in scored[:top_n]
        ]
