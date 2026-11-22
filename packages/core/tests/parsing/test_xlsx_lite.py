"""Testes de F3-T05: parser XLSX (lite)."""

from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any

import pytest
from openpyxl import Workbook
from rag_core.errors import CorruptedFile, UnsupportedType
from rag_core.interfaces import ParseLimits, Parser
from rag_core.parsing.xlsx_lite import XlsxParser
from rag_core.testing import corpus
from rag_core.types import DetectedType, StructuredDocument

PARSER = XlsxParser()


def _parse(data: bytes) -> StructuredDocument:
    return PARSER.parse(data, filename="f.xlsx", detected=DetectedType.XLSX, limits=ParseLimits())


def _xlsx(build: Any) -> bytes:
    wb = Workbook()
    build(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_prices_with_header_context() -> None:
    doc = _parse(corpus.read_bytes("A03"))
    assert isinstance(PARSER, Parser)
    assert doc.blocks[0].kind == "heading"
    assert (doc.blocks[0].text, doc.blocks[0].level) == ("Preços", 1)
    table = doc.blocks[1]
    assert table.kind == "table"
    assert table.rows is not None
    assert table.rows[0] == ("Artigo", "Preço")
    assert ("Agrafador metálico", "12,50 €") in table.rows
    assert "| Agrafador metálico | 12,50 € |" in table.text
    texts = " ".join(b.text for b in doc.blocks)
    assert "desconto de 5% em encomendas acima de 500 €" in texts
    assert "preços sem IVA (23%)" in texts


def test_inv06_hidden_sheet_skipped() -> None:
    doc = _parse(corpus.read_bytes("A03"))
    text = " ".join(b.text for b in doc.blocks)
    assert "HIDDEN-SHEET-4410" not in text
    assert "Notas" not in text
    assert "hidden_sheet_skipped" in doc.warnings
    assert any("hidden_sheet_skipped" in b.flags for b in doc.blocks)


def test_very_hidden_sheet_is_also_skipped() -> None:
    def build(wb: Any) -> None:
        wb.active.append(["visível"])
        secret = wb.create_sheet("secreta")
        secret.append(["segredo"])
        secret.sheet_state = "veryHidden"
        after = wb.create_sheet("depois")
        after.append(["x"])

    doc = _parse(_xlsx(build))
    assert [b.text for b in doc.blocks if b.kind == "heading"] == ["Sheet", "depois"]
    flagged = [b for b in doc.blocks if "hidden_sheet_skipped" in b.flags]
    assert [b.text for b in flagged] == ["depois"]  # a flag vai para o bloco seguinte


def test_salary_sheet_is_parsed_as_table() -> None:
    doc = _parse(corpus.read_bytes("A07"))
    assert doc.blocks[1].rows is not None
    assert ("Técnico Comercial", "1350 €") in doc.blocks[1].rows


def test_xlsx_large_sheet_split_with_header_repeated() -> None:
    def build(wb: Any) -> None:
        ws = wb.active
        ws.title = "Dados"
        ws.append(["id", "valor"])
        for i in range(120):
            ws.append([i, i * 2])

    doc = _parse(_xlsx(build))
    tables = [b for b in doc.blocks if b.kind == "table"]
    assert [len(t.rows or ()) for t in tables] == [51, 51, 21]
    assert all(t.rows is not None and t.rows[0] == ("id", "valor") for t in tables)
    assert tables[1].rows is not None
    assert tables[1].rows[1] == ("50", "100")
    assert [b.kind for b in doc.blocks].count("heading") == 1


def test_values_dates_empty_rows_and_columns() -> None:
    def build(wb: Any) -> None:
        ws = wb.active
        ws.title = "Mix"
        ws.append([])  # linha vazia antes do cabeçalho
        ws.append(["Dia", None, "Hora", "Taxa", "Qtd", "Ativo"])
        ws.append([date(2026, 3, 1), None, datetime(2026, 3, 1, 9, 30), 12.5, 3.0, True])
        ws.append([None, None, None, None, None, None])
        ws.append(["fim", None, None, 0.25, 7, False])

    (heading, table) = _parse(_xlsx(build)).blocks
    assert heading.text == "Mix"
    assert table.rows == (
        ("Dia", "Hora", "Taxa", "Qtd", "Ativo"),
        ("2026-03-01", "2026-03-01T09:30:00", "12.5", "3", "True"),
        ("fim", "", "0.25", "7", "False"),
    )


def test_empty_sheets_are_skipped() -> None:
    doc = _parse(_xlsx(lambda wb: wb.create_sheet("vazia")))
    assert doc.blocks == ()


def test_formula_without_cached_value_does_not_crash() -> None:
    def build(wb: Any) -> None:
        ws = wb.active
        ws.append(["a", "b"])
        ws.append([1, "=A2+1"])  # o openpyxl não calcula: sem valor em cache

    doc = _parse(_xlsx(build))
    assert doc.warnings == ("formula_without_cached_value",)
    assert doc.blocks[1].rows == (("a", "b"), ("1", ""))


def test_corrupt_and_wrong_type() -> None:
    with pytest.raises(CorruptedFile):
        _parse(b"PK\x03\x04" + b"lixo" * 20)
    with pytest.raises(UnsupportedType):
        PARSER.parse(b"x", filename="f", detected=DetectedType.PDF, limits=ParseLimits())


def test_text_helper_handles_pure_dates_and_times() -> None:
    from datetime import time

    from rag_core.parsing.xlsx_lite import _text

    assert _text(date(2026, 3, 1)) == "2026-03-01"
    assert _text(time(9, 30)) == "09:30:00"
    assert _text(datetime(2026, 3, 1, 0, 0)) == "2026-03-01"
    assert _text(3.0) == "3"
    assert _text(None) == ""
