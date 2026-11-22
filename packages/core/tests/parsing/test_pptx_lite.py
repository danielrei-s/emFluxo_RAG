"""Testes de F3-T05: parser PPTX (lite)."""

from __future__ import annotations

import io
from typing import Any

import pytest
from pptx import Presentation
from pptx.util import Inches
from rag_core.errors import CorruptedFile, UnsupportedType
from rag_core.interfaces import ParseLimits, Parser
from rag_core.parsing.pptx_lite import PptxParser
from rag_core.testing import corpus
from rag_core.types import DetectedType, StructuredDocument

PARSER = PptxParser()


def _parse(data: bytes) -> StructuredDocument:
    return PARSER.parse(data, filename="f.pptx", detected=DetectedType.PPTX, limits=ParseLimits())


def _pptx(build: Any) -> bytes:
    prs = Presentation()
    build(prs)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def test_pptx_slide_titles_and_pages() -> None:
    doc = _parse(corpus.read_bytes("A04"))
    assert isinstance(PARSER, Parser)
    assert doc.page_count == 4
    headings = [b for b in doc.blocks if b.kind == "heading"]
    assert [(h.text, h.level, h.page) for h in headings] == [
        (f"Diapositivo {n}: Aurora Distribuição ({n})", 1, n) for n in range(1, 5)
    ]
    text = " ".join(b.text for b in doc.blocks)
    for fact in (
        "fundada em 2012",
        "armazéns no Porto, em Coimbra e em Lisboa",
        "entrega em 24 horas em Portugal continental",
        "1500 clientes ativos",
    ):
        assert fact in text
    body = [b for b in doc.blocks if b.kind == "paragraph"]
    assert [b.page for b in body] == [1, 2, 3, 4]
    assert doc.title == "Aurora Distribuição (1)"


def test_notes_tables_groups_and_untitled_slides() -> None:
    def build(prs: Any) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[5])  # só título
        slide.shapes.title.text = "Com extras"
        box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(4), Inches(1))
        box.text_frame.text = "linha um\vlinha dois"
        box.text_frame.add_paragraph().text = "   "  # vazio: ignorado
        group = slide.shapes.add_group_shape()
        group.shapes.add_textbox(0, 0, Inches(2), Inches(1)).text_frame.text = "dentro do grupo"
        table = slide.shapes.add_table(2, 2, Inches(1), Inches(3), Inches(4), Inches(1)).table
        for (row, col), text in {(0, 0): "A", (0, 1): "B", (1, 0): "1", (1, 1): "2"}.items():
            table.cell(row, col).text = text
        slide.notes_slide.notes_text_frame.text = "nota do orador"

        blank = prs.slides.add_slide(prs.slide_layouts[6])  # sem título
        blank.shapes.add_textbox(0, 0, Inches(2), Inches(1)).text_frame.text = "solto"

    doc = _parse(_pptx(build))
    kinds = [(b.kind, b.text, b.page) for b in doc.blocks if b.kind != "table"]
    assert kinds == [
        ("heading", "Diapositivo 1: Com extras", 1),
        ("paragraph", "linha um linha dois", 1),
        ("paragraph", "dentro do grupo", 1),
        ("paragraph", "nota do orador", 1),
        ("heading", "Diapositivo 2", 2),
        ("paragraph", "solto", 2),
    ]
    notes = next(b for b in doc.blocks if b.text == "nota do orador")
    assert notes.flags == {"speaker_notes"}
    table = next(b for b in doc.blocks if b.kind == "table")
    assert table.rows == (("A", "B"), ("1", "2"))
    assert table.page == 1


def test_empty_presentation() -> None:
    doc = _parse(_pptx(lambda prs: None))
    assert doc.blocks == ()
    assert doc.page_count == 0
    assert doc.title is None


def test_corrupt_and_wrong_type() -> None:
    with pytest.raises(CorruptedFile):
        _parse(b"PK\x03\x04" + b"lixo" * 20)
    with pytest.raises(UnsupportedType):
        PARSER.parse(b"x", filename="f", detected=DetectedType.PDF, limits=ParseLimits())
