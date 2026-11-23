"""Sugestão de classificação pelo nome e caminho (F11-T03); o utilizador decide sempre."""

from __future__ import annotations

import re
import unicodedata

RESTRICTED = (
    "rh", "recursos humanos", "salario", "vencimento", "contrato", "nif", "iban",
    "saude", "medico", "pessoal",
)  # fmt: skip
CONFIDENTIAL = ("confidencial", "cliente")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _contains(haystack: str, term: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", haystack) is not None


def suggest_classification(rel_path: str) -> str:
    """``restricted`` > ``confidential`` > ``internal``, ignorando acentos e maiúsculas."""
    text = _fold(rel_path.replace("\\", "/"))
    text = re.sub(r"[_\-./]+", " ", text)
    if any(_contains(text, term) for term in RESTRICTED):
        return "restricted"
    if any(_contains(text, term) for term in CONFIDENTIAL):
        return "confidential"
    return "internal"
