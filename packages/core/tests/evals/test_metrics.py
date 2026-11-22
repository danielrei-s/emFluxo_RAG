"""Testes de F5-T04: métricas de avaliação (valores calculados à mão)."""

from __future__ import annotations

import math

import pytest
from rag_core.evals import metrics as m


def test_metrics_hand_computed() -> None:
    retrieved = ["d3", "d1", "d9", "d2"]
    expected = {"d1", "d2"}
    assert m.recall_at_k(retrieved, expected, 1) == 0.0
    assert m.recall_at_k(retrieved, expected, 2) == 0.5  # só o d1 está nos 2 primeiros
    assert m.recall_at_k(retrieved, expected, 4) == 1.0
    assert m.mrr(retrieved, expected) == 0.5  # o primeiro relevante está na posição 2
    assert m.mrr(["x", "y"], expected) == 0.0
    # relevantes nas posições 2 e 4; o ideal tem-nos nas posições 1 e 2
    dcg = 1 / math.log2(3) + 1 / math.log2(5)
    ideal = 1 / math.log2(2) + 1 / math.log2(3)
    assert m.ndcg_at_k(retrieved, expected, 4) == pytest.approx(dcg / ideal)
    assert m.ndcg_at_k(["d1", "d2"], expected, 5) == pytest.approx(1.0)
    assert m.ndcg_at_k(["x"], expected, 5) == 0.0
    # k menor que o número de relevantes: o ideal só conta k posições
    assert m.ndcg_at_k(["d1", "d2"], {"d1", "d2", "d3"}, 2) == pytest.approx(1.0)
    # repetições não contam duas vezes
    assert m.ndcg_at_k(["d1", "d1", "d2"], expected, 3) == pytest.approx(
        (1 + 1 / math.log2(4)) / ideal
    )


def test_expected_documents_are_required() -> None:
    with pytest.raises(ValueError):
        m.recall_at_k(["a"], set(), 5)
    with pytest.raises(ValueError):
        m.ndcg_at_k(["a"], set(), 5)


def test_rates() -> None:
    assert m.fallback_rate([True, False, False, False]) == 0.25
    assert m.citation_validity_rate([True, False, False, False]) == 0.75
    assert m.fallback_rate([]) == 0.0 and m.citation_validity_rate([]) == 1.0
    assert m.not_found_accuracy(["not_found", "grounded", "not_found", "refused"]) == 0.5
    assert m.not_found_accuracy([]) == 0.0
    assert m.answer_contains_rate([True, True, False]) == pytest.approx(2 / 3)
    assert m.answer_contains_rate([]) == 0.0
    assert m.leak_rate([False, True]) == 0.5 and m.leak_rate([]) == 0.0


def test_text_matching_ignores_case_and_whitespace() -> None:
    assert m.answer_contains("Tem  25 dias\núteis de FÉRIAS", ["25 dias", "férias"])
    assert not m.answer_contains("Tem 25 dias", ["25 dias", "30 dias"])
    assert m.answer_contains("qualquer texto", [])
    assert m.leaks("O código é 0000.", ["PWNED-7781", "0000"])
    assert not m.leaks("Nada de especial", ["CANARIO-RH"])
    assert not m.leaks("texto", [])


def test_median() -> None:
    assert m.median([]) == 0.0
    assert m.median([5.0]) == 5.0
    assert m.median([9.0, 1.0, 5.0]) == 5.0
    assert m.median([1.0, 3.0, 5.0, 100.0]) == 4.0
