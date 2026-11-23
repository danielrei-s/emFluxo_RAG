"""Testes de F13-T08: documentos legais são rascunhos assinalados como tal."""

from __future__ import annotations

from pathlib import Path

LEGAL = Path(__file__).resolve().parents[2] / "docs" / "legal"
EXPECTED = {
    "dpa-modelo.md",
    "politica-privacidade.md",
    "termos-servico.md",
    "dpia-modelo.md",
    "politica-uso-ia.md",
    "politica-retencao.md",
}


def test_all_legal_docs_exist() -> None:
    assert {p.name for p in LEGAL.glob("*.md")} == EXPECTED


def test_legal_docs_marked_draft() -> None:
    for name in EXPECTED:
        text = (LEGAL / name).read_text(encoding="utf-8")
        assert text.startswith("> **RASCUNHO — validar com advogado.**"), name


def test_legal_docs_match_the_architecture() -> None:
    privacy = (LEGAL / "politica-privacidade.md").read_text(encoding="utf-8")
    retention = (LEGAL / "politica-retencao.md").read_text(encoding="utf-8")
    assert "0, 30 ou 90" in privacy and "0, 30 ou 90" in retention
    dpa = (LEGAL / "dpa-modelo.md").read_text(encoding="utf-8")
    assert "UE" in dpa and "restricted" in dpa and "RLS" in dpa
