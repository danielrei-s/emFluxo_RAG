"""Métricas de avaliação (F5-T04): puras e calculáveis à mão. Relevância binária por documento."""

from __future__ import annotations

import math
import re
from collections.abc import Collection, Sequence

_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    return _SPACES.sub(" ", text).strip().casefold()


def recall_at_k(retrieved: Sequence[str], expected: Collection[str], k: int) -> float:
    """Fração dos documentos esperados que aparecem nos ``k`` primeiros resultados."""
    if not expected:
        raise ValueError("recall precisa de pelo menos um documento esperado")
    return len(set(retrieved[:k]) & set(expected)) / len(set(expected))


def mrr(retrieved: Sequence[str], expected: Collection[str]) -> float:
    """Inverso da posição (desde 1) do primeiro documento relevante; 0 se nenhum aparece."""
    wanted = set(expected)
    for position, doc_id in enumerate(retrieved, start=1):
        if doc_id in wanted:
            return 1.0 / position
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], expected: Collection[str], k: int) -> float:
    """NDCG com relevância binária (ganho ``1/log2(posição+1)``), sem repetir documentos."""
    wanted = set(expected)
    if not wanted:
        raise ValueError("ndcg precisa de pelo menos um documento esperado")
    seen: set[str] = set()
    dcg = 0.0
    for position, doc_id in enumerate(retrieved[:k], start=1):
        if doc_id in wanted and doc_id not in seen:
            dcg += 1.0 / math.log2(position + 1)
        seen.add(doc_id)
    ideal = sum(1.0 / math.log2(p + 1) for p in range(1, min(len(wanted), k) + 1))
    return dcg / ideal


def fallback_rate(fell_back: Sequence[bool]) -> float:
    """Fração de respostas que caíram no "não encontrei" por citação inválida."""
    return sum(fell_back) / len(fell_back) if fell_back else 0.0


def citation_validity_rate(fell_back: Sequence[bool]) -> float:
    """Fração de respostas sem falha de validação de citações (1 - taxa de fallback)."""
    return 1.0 - fallback_rate(fell_back) if fell_back else 1.0


def not_found_accuracy(kinds: Sequence[str]) -> float:
    """Entre as perguntas sem resposta, fração em que o sistema respondeu "não encontrei"."""
    return sum(1 for k in kinds if k == "not_found") / len(kinds) if kinds else 0.0


def answer_contains(text: str, needles: Sequence[str]) -> bool:
    """Todas as strings esperadas aparecem (sem distinguir maiúsculas nem espaços)."""
    haystack = normalize(text)
    return all(normalize(needle) in haystack for needle in needles)


def answer_contains_rate(results: Sequence[bool]) -> float:
    return sum(results) / len(results) if results else 0.0


def leaks(text: str, forbidden: Sequence[str]) -> bool:
    """Alguma string proibida (``must_not_contain``) aparece na resposta."""
    haystack = normalize(text)
    return any(normalize(item) in haystack for item in forbidden)


def leak_rate(flags: Sequence[bool]) -> float:
    return sum(flags) / len(flags) if flags else 0.0


def median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
