"""Citações: extração e validação (INV-07)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from rag_core.generation.constants import GENERAL_KNOWLEDGE_MARKER, NOT_FOUND
from rag_core.interfaces import TenantPolicy
from rag_core.text import normalize_tokens
from rag_core.types import AnswerKind

_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
WEAK_SUPPORT_THRESHOLD = 0.15
WEAK_SUPPORT = "weak_support"


@dataclass(frozen=True)
class Validation:
    """Resultado da validação de uma resposta do LLM."""

    kind: AnswerKind
    ok: bool
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def parse_citations(text: str) -> list[int]:
    """Índices citados, por ordem de aparição e sem repetidos (``[1]``, ``[1, 2]``, ``[1][2]``)."""
    found: list[int] = []
    for match in _CITATION.finditer(text):
        for number in match.group(1).split(","):
            index = int(number)
            if index not in found:
                found.append(index)
    return found


def _weak_support(text: str, excerpts: Mapping[int, str]) -> bool:
    for sentence in _SENTENCE.split(text):
        cited = [i for i in parse_citations(sentence) if i in excerpts]
        tokens = set(normalize_tokens(_CITATION.sub(" ", sentence)))
        if not cited or not tokens:
            continue
        best = max(len(tokens & set(normalize_tokens(excerpts[i]))) / len(tokens) for i in cited)
        if best < WEAK_SUPPORT_THRESHOLD:
            return True
    return False


def validate(
    text: str,
    n: int,
    policy: TenantPolicy,
    sentinel: str,
    excerpts: Mapping[int, str] | None = None,
) -> Validation:
    """Valida a resposta contra os ``n`` excertos enviados (INV-07)."""
    if sentinel and sentinel in text:
        return Validation("refused", False, ("sentinel_leak",))
    stripped = text.strip()
    if stripped.startswith(NOT_FOUND):
        return Validation("not_found", True)
    citations = parse_citations(stripped)
    if stripped.startswith(GENERAL_KNOWLEDGE_MARKER):
        if policy.general_knowledge != "labeled":
            return Validation("general_knowledge", False, ("general_knowledge_forbidden",))
        if citations:
            return Validation("general_knowledge", False, ("citations_in_general_knowledge",))
        return Validation("general_knowledge", True)
    if not citations:
        return Validation("grounded", False, ("no_citation",))
    if any(not 1 <= i <= n for i in citations):
        return Validation("grounded", False, ("citation_out_of_range",))
    warnings = (WEAK_SUPPORT,) if excerpts and _weak_support(stripped, excerpts) else ()
    return Validation("grounded", True, warnings=warnings)
