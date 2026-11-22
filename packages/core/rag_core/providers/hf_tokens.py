"""Contagem de tokens com o tokenizer real do modelo de embeddings (F5-T02)."""

from __future__ import annotations

from pathlib import Path


class HfTokenCounter:
    """``tokenizers`` (extra ``onnx``): usado pelo chunker em produção."""

    def __init__(self, tokenizer_file: Path) -> None:
        from tokenizers import Tokenizer

        self._tokenizer = Tokenizer.from_file(str(tokenizer_file))

    def count(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)
