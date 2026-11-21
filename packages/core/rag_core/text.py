"""Tokenização partilhada (keyword search, reranker falso, embedder falso)."""

from __future__ import annotations

import re
import unicodedata

_SPLIT_RE = re.compile(r"[\W_]+")


def strip_diacritics(text: str) -> str:
    """Remove acentos e outros sinais combinados (NFKD)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_tokens(s: str) -> list[str]:
    """Minúsculas, sem diacríticos, separado em não alfanuméricos; descarta tokens de 1 carácter."""
    folded = strip_diacritics(s).lower()
    return [token for token in _SPLIT_RE.split(folded) if len(token) > 1]
