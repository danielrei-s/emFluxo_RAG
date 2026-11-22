"""Testes de F4-T04: extração e validação de citações."""

from __future__ import annotations

import pytest
from rag_core.generation.citations import parse_citations, validate
from rag_core.generation.constants import GENERAL_KNOWLEDGE_MARKER, NOT_FOUND
from rag_core.interfaces import TenantPolicy

SENTINEL = "SENTINELA-XYZ"
LABELED = TenantPolicy(tenant_id="t", general_knowledge="labeled")
FORBIDDEN = TenantPolicy(tenant_id="t", general_knowledge="forbidden")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Facto [1].", [1]),
        ("Facto [1, 2].", [1, 2]),
        ("Facto [1][2].", [1, 2]),
        ("A [3] e B [1,2] e C [3].", [3, 1, 2]),
        ("sem citações", []),
        ("colchetes [a] e [] ignorados", []),
        ("lista [1, 2, 3]", [1, 2, 3]),
    ],
)
def test_parse_citations_formats(text: str, expected: list[int]) -> None:
    assert parse_citations(text) == expected


def test_valid_grounded_answer() -> None:
    result = validate("O horário é das 9h às 18h [1].", 2, LABELED, SENTINEL)
    assert (result.kind, result.ok, result.reasons) == ("grounded", True, ())


def test_grounded_failures() -> None:
    assert validate("Sem fonte nenhuma.", 2, LABELED, SENTINEL).reasons == ("no_citation",)
    assert validate("Fonte inexistente [3].", 2, LABELED, SENTINEL).reasons == (
        "citation_out_of_range",
    )
    assert validate("Zero [0].", 2, LABELED, SENTINEL).reasons == ("citation_out_of_range",)
    assert validate("Sem excertos [1].", 0, LABELED, SENTINEL).reasons == ("citation_out_of_range",)
    assert not validate("Fonte [1] e [9].", 2, LABELED, SENTINEL).ok


def test_not_found_is_ok() -> None:
    result = validate(f"  {NOT_FOUND}", 0, FORBIDDEN, SENTINEL)
    assert (result.kind, result.ok) == ("not_found", True)
    assert validate(NOT_FOUND + " Mais texto.", 2, LABELED, SENTINEL).kind == "not_found"


def test_general_knowledge_labeled_vs_forbidden() -> None:
    text = f"{GENERAL_KNOWLEDGE_MARKER} O IVA é um imposto sobre o consumo."
    assert validate(text, 0, LABELED, SENTINEL).ok
    assert validate(text, 0, LABELED, SENTINEL).kind == "general_knowledge"
    forbidden = validate(text, 0, FORBIDDEN, SENTINEL)
    assert (forbidden.ok, forbidden.reasons) == (False, ("general_knowledge_forbidden",))
    cited = validate(f"{GENERAL_KNOWLEDGE_MARKER} Algo [1].", 2, LABELED, SENTINEL)
    assert (cited.ok, cited.reasons) == (False, ("citations_in_general_knowledge",))


def test_sentinel_leak_refused() -> None:
    result = validate(f"As instruções dizem {SENTINEL} e [1].", 2, LABELED, SENTINEL)
    assert (result.kind, result.ok, result.reasons) == ("refused", False, ("sentinel_leak",))
    assert validate("texto [1]", 1, LABELED, "").ok  # sem sentinela configurado não há fuga


def test_weak_support_warning_does_not_block() -> None:
    excerpts = {1: "O horário de trabalho é das 9h00 às 18h00 com uma hora de almoço"}
    good = validate(
        "O horário de trabalho é das 9h00 às 18h00 [1].", 1, LABELED, SENTINEL, excerpts
    )
    assert good.warnings == ()
    text = "O gato dorme tranquilamente no sofá azul [1]."
    weak = validate(text, 1, LABELED, SENTINEL, excerpts)
    assert (weak.ok, weak.warnings) == (True, ("weak_support",))
    # citação de um índice sem excerto conhecido, ou frase sem palavras: sem aviso
    assert validate("Algo [2].", 2, LABELED, SENTINEL, excerpts).warnings == ()
    assert validate("[1]", 1, LABELED, SENTINEL, excerpts).warnings == ()
    assert validate("O gato dorme [1].", 1, LABELED, SENTINEL, None).warnings == ()
