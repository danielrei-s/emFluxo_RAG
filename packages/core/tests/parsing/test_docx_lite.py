"""Testes de F3-T04: parser DOCX (lite)."""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any

import pytest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from rag_core.errors import CorruptedFile, UnsupportedType
from rag_core.interfaces import ParseLimits, Parser
from rag_core.parsing.docx_lite import DocxParser
from rag_core.testing import corpus
from rag_core.types import DetectedType, StructuredDocument

PARSER = DocxParser()


def _parse(data: bytes) -> StructuredDocument:
    return PARSER.parse(data, filename="f.docx", detected=DetectedType.DOCX, limits=ParseLimits())


def _build(fill: Callable[[Any], None]) -> bytes:
    doc = Document()
    fill(doc)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_docx_headings_and_table_order() -> None:
    doc = _parse(corpus.read_bytes("A02"))
    assert isinstance(PARSER, Parser)
    assert [(b.kind, b.text) for b in doc.blocks[:2]] == [
        ("heading", "Política de Despesas"),
        ("paragraph", "A refeição em deslocação até 15,00 €; a quilometragem a 0,40 € por km."),
    ]
    assert doc.blocks[0].level == 1
    assert doc.blocks[1].page is None
    kinds = [b.kind for b in doc.blocks]
    assert kinds == ["heading", "paragraph", "paragraph", "table"]  # a tabela vem no fim
    table = doc.blocks[3]
    assert table.rows == (
        ("Regra", "Detalhe"),
        ("Aprovação", "despesas acima de 200 € exigem aprovação do diretor financeiro"),
    )
    assert "reembolso até ao dia 10 do mês seguinte" in doc.blocks[2].text
    assert doc.title == "Política de Despesas"
    assert doc.warnings == ()


def test_inv06_hidden_runs_removed() -> None:
    doc = _parse(corpus.read_bytes("A09"))
    text = " ".join(b.text for b in doc.blocks)
    assert "HIDDEN-5521" not in text
    assert "INSTRUÇÃO OCULTA" not in text
    assert "0000" not in text
    assert text.strip() == "O código de acesso à sala de reuniões é pedido na receção."
    assert [b.flags for b in doc.blocks] == [frozenset({"hidden_text_removed"})]
    assert doc.warnings == ("hidden_text_removed",)


def test_fully_hidden_paragraph_flags_next_block_and_trailing_flags_last() -> None:
    def fill(doc: Any) -> None:
        doc.add_paragraph("antes")
        run = doc.add_paragraph().add_run("segredo oculto")
        run.font.hidden = True
        doc.add_paragraph("depois")
        tiny = doc.add_paragraph().add_run("pequeno")
        tiny.font.size = Pt(1.5)

    doc = _parse(_build(fill))
    assert [b.text for b in doc.blocks] == ["antes", "depois"]
    assert [bool(b.flags) for b in doc.blocks] == [False, True]  # "depois" + final no último


def test_visible_formatting_is_not_treated_as_hidden() -> None:
    def fill(doc: Any) -> None:
        para = doc.add_paragraph()
        para.add_run("preto ").font.color.rgb = RGBColor(0, 0, 0)
        para.add_run("pequeno mas legível").font.size = Pt(8)

    doc = _parse(_build(fill))
    assert doc.blocks[0].text == "preto pequeno mas legível"
    assert doc.blocks[0].flags == frozenset()


def test_portuguese_heading_style() -> None:
    def fill(doc: Any) -> None:
        for name in ("Título 1", "Título 2", "Título"):
            doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        doc.add_paragraph("Documento", style="Título")
        doc.add_paragraph("Capítulo", style="Título 1")
        doc.add_paragraph("Secção", style="Título 2")
        doc.add_paragraph("texto")

    doc = _parse(_build(fill))
    assert [(b.kind, b.level, b.text) for b in doc.blocks] == [
        ("heading", 1, "Documento"),
        ("heading", 1, "Capítulo"),
        ("heading", 2, "Secção"),
        ("paragraph", None, "texto"),
    ]
    assert doc.title == "Documento"


def test_outline_level_and_lists_and_title_fallback() -> None:
    def fill(doc: Any) -> None:
        outline = doc.add_paragraph("Por outline")
        level = OxmlElement("w:outlineLvl")
        level.set(qn("w:val"), "2")
        outline._p.get_or_add_pPr().append(level)
        deep = doc.add_paragraph("Muito fundo")
        deeper = OxmlElement("w:outlineLvl")
        deeper.set(qn("w:val"), "8")
        deep._p.get_or_add_pPr().append(deeper)
        numbered = doc.add_paragraph("com numeração")
        numbered._p.get_or_add_pPr().append(OxmlElement("w:numPr"))
        doc.add_paragraph("com estilo", style="List Bullet")
        doc.add_heading("Primeiro nível", 1)

    doc = _parse(_build(fill))
    assert [(b.kind, b.level) for b in doc.blocks] == [
        ("heading", 3),
        ("heading", 6),
        ("list_item", None),
        ("list_item", None),
        ("heading", 1),
    ]
    assert doc.title == "Primeiro nível"


def test_merged_cells_appear_once_and_empty_rows_are_skipped() -> None:
    def fill(doc: Any) -> None:
        table = doc.add_table(rows=3, cols=3)
        table.cell(0, 0).merge(table.cell(0, 1)).text = "Junto"
        table.cell(0, 2).text = "C"
        for col, text in enumerate(("a", "b", "c")):
            table.cell(1, col).text = text
        # linha 2 fica vazia

    doc = _parse(_build(fill))
    (table,) = doc.blocks
    assert table.rows == (("Junto", "C"), ("a", "b", "c"))


def test_injection_text_is_kept_but_visible_text_only() -> None:
    doc = _parse(corpus.read_bytes("A08"))
    text = " ".join(b.text for b in doc.blocks)
    assert "campanha de regresso às aulas em setembro" in text
    assert "PWNED-7781" in text  # visível: fica; a deteção é em F3-T12
    assert doc.blocks[0].kind == "heading"


def test_hidden_text_inside_table_cell_is_removed() -> None:
    def fill(doc: Any) -> None:
        table = doc.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "visível"
        run = table.cell(0, 1).paragraphs[0].add_run("oculto")
        run.font.hidden = True

    doc = _parse(_build(fill))
    assert doc.blocks[0].rows == (("visível", ""),)
    assert doc.blocks[0].flags == {"hidden_text_removed"}


def test_corrupt_and_wrong_type() -> None:
    with pytest.raises(CorruptedFile):
        _parse(b"PK\x03\x04" + b"lixo" * 20)
    with pytest.raises(UnsupportedType):
        PARSER.parse(b"x", filename="f", detected=DetectedType.PDF, limits=ParseLimits())


def test_fully_hidden_table_flags_next_block() -> None:
    def fill(doc: Any) -> None:
        table = doc.add_table(rows=1, cols=1)
        table.cell(0, 0).paragraphs[0].add_run("oculto").font.hidden = True
        doc.add_paragraph("depois")

    doc = _parse(_build(fill))
    assert [(b.text, bool(b.flags)) for b in doc.blocks] == [("depois", True)]
