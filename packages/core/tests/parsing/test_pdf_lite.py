"""Testes de F3-T06: parser PDF (lite)."""

from __future__ import annotations

import io
from typing import Any

import pytest
from rag_core.errors import CorruptedFile, EncryptedFile, UnsupportedType, ValidationFailed
from rag_core.interfaces import ParseLimits, Parser
from rag_core.parsing.pdf_lite import PdfParser, hidden_text_spans
from rag_core.testing import corpus
from rag_core.types import DetectedType, StructuredDocument
from reportlab.pdfgen import canvas

PARSER = PdfParser()
INVALID = corpus.CORPUS_DIR / "invalid"


def _parse(data: bytes, limits: ParseLimits | None = None) -> StructuredDocument:
    return PARSER.parse(
        data, filename="f.pdf", detected=DetectedType.PDF, limits=limits or ParseLimits()
    )


def _pdf(draw: Any) -> bytes:
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, invariant=1)
    draw(pdf)
    pdf.save()
    return buf.getvalue()


def test_pdf_facts_with_page_numbers() -> None:
    doc = _parse(corpus.read_bytes("A01"))
    assert isinstance(PARSER, Parser)
    assert doc.page_count == 3
    by_page: dict[int | None, str] = {}
    for block in doc.blocks:
        by_page[block.page] = by_page.get(block.page, "") + " " + block.text
    assert "horário de trabalho é das 9h00 às 18h00, com 1 hora de almoço" in by_page[2]
    assert "25 dias úteis de férias por ano" in by_page[2]
    assert "teletrabalho até 2 dias por semana" in by_page[3]
    assert "pedidos de férias com 30 dias de antecedência no portal RH" in by_page[3]
    assert "horário" not in by_page[3]
    assert doc.warnings == ()
    assert all(not b.flags for b in doc.blocks)


def test_inv06_white_and_tiny_text_removed() -> None:
    def draw(pdf: Any) -> None:
        pdf.drawString(50, 780, "Texto visível normal.")
        pdf.setFillColorRGB(1, 1, 1)
        pdf.drawString(50, 750, "branco rgb HIDDEN-PDF-0001")
        pdf.setFillGray(1)
        pdf.drawString(50, 720, "branco cinza HIDDEN-PDF-0002")
        pdf.setFillColorCMYK(0, 0, 0, 0)
        pdf.drawString(50, 690, "branco cmyk HIDDEN-PDF-0003")
        pdf.setFillColorRGB(0, 0, 0)
        pdf.setFont("Helvetica", 0.5)
        pdf.drawString(50, 660, "minusculo HIDDEN-PDF-0004")
        pdf.setFont("Helvetica", 12)
        pdf.setFillColorRGB(0.2, 0.2, 0.2)
        pdf.drawString(50, 630, "cinzento escuro continua visível")
        pdf.showPage()

    data = _pdf(draw)
    doc = _parse(data)
    text = " ".join(b.text for b in doc.blocks)
    assert "HIDDEN-PDF" not in text
    assert "Texto visível normal." in text
    assert "cinzento escuro continua visível" in text
    assert any("hidden_text_removed" in b.flags for b in doc.blocks)
    assert doc.warnings == ("hidden_text_removed",)

    spans = hidden_text_spans(data)
    for n in range(1, 5):
        assert any(f"HIDDEN-PDF-000{n}" in s for s in spans)
    assert all("visível" not in s for s in spans)
    assert hidden_text_spans(corpus.read_bytes("A01")) == []


def test_paragraphs_split_on_vertical_gaps() -> None:
    def draw(pdf: Any) -> None:
        pdf.setFont("Helvetica", 12)
        for y, line in [(780, "primeira linha"), (765, "continua"), (700, "outro parágrafo")]:
            pdf.drawString(50, y, line)
        pdf.showPage()

    doc = _parse(_pdf(draw))
    assert [b.text for b in doc.blocks] == ["primeira linha continua", "outro parágrafo"]
    assert all(b.kind == "paragraph" and b.page == 1 for b in doc.blocks)


def test_bookmarks_become_headings_at_page_start() -> None:
    def draw(pdf: Any) -> None:
        pdf.bookmarkPage("p1")
        pdf.addOutlineEntry("Capítulo Um", "p1", level=0)
        pdf.drawString(50, 780, "texto da página um com conteúdo suficiente")
        pdf.showPage()
        pdf.bookmarkPage("p2")
        pdf.addOutlineEntry("Secção Dois", "p2", level=1)
        pdf.drawString(50, 780, "texto da página dois com conteúdo suficiente")
        pdf.showPage()

    doc = _parse(_pdf(draw))
    assert [(b.kind, b.level, b.page, b.text) for b in doc.blocks if b.kind == "heading"] == [
        ("heading", 1, 1, "Capítulo Um"),
        ("heading", 2, 2, "Secção Dois"),
    ]
    assert [b.kind for b in doc.blocks] == ["heading", "paragraph", "heading", "paragraph"]


def test_encrypted_pdf_raises() -> None:
    with pytest.raises(EncryptedFile):
        _parse((INVALID / "encrypted.pdf").read_bytes())


def test_truncated_pdf_raises() -> None:
    with pytest.raises(CorruptedFile):
        _parse((INVALID / "truncated.pdf").read_bytes())
    with pytest.raises(CorruptedFile):
        _parse(b"%PDF-1.4 isto nao e um pdf")


def test_scanned_page_flagged_needs_ocr() -> None:
    doc = _parse(corpus.read_bytes("A10"))
    assert doc.page_count == 1
    assert len(doc.blocks) == 1
    block = doc.blocks[0]
    assert (block.kind, block.text, block.page) == ("paragraph", "", 1)
    assert block.flags == {"needs_ocr"}


def test_mixed_document_flags_only_the_empty_page() -> None:
    def draw(pdf: Any) -> None:
        pdf.drawString(50, 780, "uma página com texto de sobra para passar")
        pdf.showPage()
        pdf.drawString(50, 780, "curto")
        pdf.showPage()

    blocks = _parse(_pdf(draw)).blocks
    assert [(b.page, b.flags) for b in blocks] == [(1, frozenset()), (2, {"needs_ocr"})]


def test_too_many_pages_and_wrong_type() -> None:
    with pytest.raises(ValidationFailed) as exc:
        _parse(corpus.read_bytes("A01"), ParseLimits(max_pages=2))
    assert exc.value.subcode == "too_many_pages"
    with pytest.raises(UnsupportedType):
        PARSER.parse(b"x", filename="f", detected=DetectedType.DOCX, limits=ParseLimits())


def test_is_hidden_char_color_models_and_non_chars() -> None:
    from rag_core.parsing.pdf_lite import is_hidden_char

    def char(color: Any, size: Any = 12) -> dict[str, Any]:
        return {"object_type": "char", "non_stroking_color": color, "size": size}

    assert is_hidden_char(char(1))  # cinzento escalar
    assert is_hidden_char(char([1, 1, 1]))
    assert is_hidden_char(char((0, 0, 0, 0)))
    assert is_hidden_char(char((0,), size=0.5))
    assert not is_hidden_char(char((0, 0, 0)))
    assert not is_hidden_char(char((0, 0, 0, 1)))
    assert not is_hidden_char(char((1, 1)))  # modelo desconhecido
    assert not is_hidden_char(char("Pattern1"))  # padrão (não numérico)
    assert not is_hidden_char(char(None, size=None))
    assert not is_hidden_char({"object_type": "rect", "non_stroking_color": (1, 1, 1)})


def test_hidden_span_at_end_of_page() -> None:
    def draw(pdf: Any) -> None:
        pdf.drawString(50, 780, "visível")
        pdf.setFillGray(1)
        pdf.drawString(50, 750, "HIDDEN-PDF-0009")
        pdf.showPage()

    assert hidden_text_spans(_pdf(draw)) == ["HIDDEN-PDF-0009"]


def test_paragraph_helper_skips_blank_lines() -> None:
    from rag_core.parsing.pdf_lite import _paragraphs

    class FakePage:
        def extract_text_lines(self, **_: Any) -> list[dict[str, Any]]:
            return [
                {"text": "a", "top": 0, "bottom": 10},
                {"text": "   ", "top": 11, "bottom": 21},
                {"text": "b", "top": 12, "bottom": 22},
            ]

    assert _paragraphs(FakePage()) == ["a b"]


def test_errors_while_reading_pages_become_corrupted(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_page: Any) -> list[str]:
        raise ValueError("falha a meio")

    monkeypatch.setattr("rag_core.parsing.pdf_lite._paragraphs", boom)
    with pytest.raises(CorruptedFile):
        _parse(corpus.read_bytes("A01"))
