"""Testes de F3-T09: adaptador Docling (unitários com conversor falso; reais: marcador docling)."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from rag_core.errors import CorruptedFile, EncryptedFile, UnsupportedType, ValidationFailed
from rag_core.interfaces import ParseLimits
from rag_core.parsing import docling_full
from rag_core.parsing.docling_full import (
    DoclingParser,
    full_registry,
    map_document,
    remove_hidden_spans,
)
from rag_core.testing import corpus
from rag_core.types import Block, DetectedType
from reportlab.pdfgen import canvas

ALL = frozenset(DetectedType)


def _item(label: str, text: str = "", page: int | None = None, **extra: Any) -> Any:
    prov = [SimpleNamespace(page_no=page)] if page else []
    return SimpleNamespace(label=SimpleNamespace(name=label), text=text, prov=prov, **extra)


def _table(rows: list[list[str]], page: int | None = 1) -> Any:
    grid = [[SimpleNamespace(text=c) for c in row] for row in rows]
    return _item("TABLE", page=page, data=SimpleNamespace(grid=grid))


def _doc(items: list[Any], pages: int | None = None) -> Any:
    return SimpleNamespace(
        iterate_items=lambda: [(i, 0) for i in items],
        pages={n: object() for n in range(pages)} if pages else {},
    )


class FakeConverter:
    def __init__(self, document: Any) -> None:
        self.document = document
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def convert(self, stream: Any, **kwargs: Any) -> Any:
        self.calls.append((stream, kwargs))
        return SimpleNamespace(document=self.document)


def _parser(
    tmp_path: Path, converter: Any, supported: frozenset[DetectedType] = ALL
) -> DoclingParser:
    return DoclingParser(tmp_path, converter_factory=lambda *_: converter, supported=supported)


@pytest.fixture(autouse=True)
def _no_real_stream(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem o extra, o DocumentStream não existe: o conversor falso recebe (nome, bytes)."""
    if request.node.get_closest_marker("docling") is None:
        monkeypatch.setattr(docling_full, "_document_stream", lambda name, data: (name, data))


# ------------------------------------------------------------------------ mapeamento


def test_map_document_labels_levels_pages_and_tables() -> None:
    doc = _doc(
        [
            _item("TITLE", "  Título   do doc ", 1),
            _item("SECTION_HEADER", "Secção", 1, level=2),
            _item("SECTION_HEADER", "Fundo", 1, level=9),
            _item("SECTION_HEADER", "Sem nível", 2, level=None),
            _item("TEXT", "um\n parágrafo", 2),
            _item("FOOTNOTE", "nota", 2),
            _item("LIST_ITEM", "item", 2),
            _item("PICTURE", "texto na imagem", 3),
            _item("PICTURE", "", 3),
            _item("PAGE_FOOTER", "rodapé", 3),
            _table([["a", "b"], ["", ""], ["1", "2"]], 3),
            _table([["", ""]], 3),
        ],
        pages=3,
    )
    blocks, title, pages = map_document(doc)
    assert title == "Título do doc"
    assert pages == 3
    assert [(b.kind, b.level, b.page, b.text) for b in blocks[:8]] == [
        ("heading", 1, 1, "Título do doc"),
        ("heading", 2, 1, "Secção"),
        ("heading", 6, 1, "Fundo"),
        ("heading", 1, 2, "Sem nível"),
        ("paragraph", None, 2, "um parágrafo"),
        ("paragraph", None, 2, "nota"),
        ("list_item", None, 2, "item"),
        ("image_text", None, 3, "texto na imagem"),
    ]
    table = blocks[8]
    assert table.rows == (("a", "b"), ("1", "2"))
    assert table.page == 3
    assert len(blocks) == 9
    assert map_document(_doc([]))[1:] == (None, None)


def test_remove_hidden_spans() -> None:
    blocks = [
        Block(kind="paragraph", text="visível HIDDEN-PDF-1 fim", page=1),
        Block(kind="paragraph", text="HIDDEN-PDF-1", page=1),
        Block(kind="paragraph", text="limpo", page=2),
        Block(kind="table", text="| a |", rows=(("a",),), page=2),
    ]
    result, changed = remove_hidden_spans(blocks, ["HIDDEN-PDF-1"])
    assert changed
    assert [b.text for b in result] == ["visível fim", "limpo", "| a |"]
    assert result[0].flags == {"hidden_text_removed"}
    assert result[1].flags == frozenset()
    assert remove_hidden_spans(blocks, []) == (blocks, False)
    assert remove_hidden_spans(blocks, ["ausente"])[1] is False


# ------------------------------------------------------------------------ o parser


def test_parser_converts_and_cleans(tmp_path: Path) -> None:
    converter = FakeConverter(
        _doc(
            [
                _item("TITLE", "T​ítulo", 1),
                _item("TEXT", "ola​ mundo", 1),
                _item("TEXT", "​", 1),
                _table([["x​", "y"], ["1", "2"]], 1),
            ],
            pages=2,
        )
    )
    parser = _parser(tmp_path, converter)
    limits = ParseLimits(max_pages=7, max_bytes=999)
    doc = parser.parse(b"%PDF-", filename="a.pdf", detected=DetectedType.HTML, limits=limits)
    assert doc.title == "Título"
    assert [b.text for b in doc.blocks][:2] == ["Título", "ola mundo"]
    assert doc.blocks[2].rows == (("x", "y"), ("1", "2"))
    assert doc.page_count == 2
    assert (doc.parser_name, doc.warnings) == ("full-docling", ())
    ((stream, kwargs),) = converter.calls
    assert stream[0] == "a.pdf"
    assert kwargs == {"max_num_pages": 7, "max_file_size": 999}


def test_converters_are_built_once_per_ocr_setting(tmp_path: Path) -> None:
    built: list[tuple[Path, bool, float]] = []

    def factory(path: Path, ocr: bool, timeout: float) -> FakeConverter:
        built.append((path, ocr, timeout))
        return FakeConverter(_doc([]))

    parser = DoclingParser(tmp_path, converter_factory=factory, supported=ALL)
    for limits in (ParseLimits(), ParseLimits(), ParseLimits(ocr=True, timeout_s=5)):
        parser.parse(b"x", filename="f.docx", detected=DetectedType.PNG, limits=limits)
    assert built == [(tmp_path, False, 120.0), (tmp_path, True, 5)]


def test_missing_artifacts_and_unsupported_type(tmp_path: Path) -> None:
    with pytest.raises(ValidationFailed) as exc:
        DoclingParser(tmp_path / "nao-existe", supported=ALL)
    assert exc.value.subcode == "docling_artifacts_missing"
    parser = _parser(tmp_path, FakeConverter(_doc([])), frozenset({DetectedType.PDF}))
    with pytest.raises(UnsupportedType):
        parser.parse(b"x", filename="f.txt", detected=DetectedType.TXT, limits=ParseLimits())


@pytest.mark.parametrize(
    ("message", "error"),
    [
        ("File is password protected", EncryptedFile),
        ("document is Encrypted", EncryptedFile),
        ("Number of pages exceeds the limit", ValidationFailed),
        ("boom", CorruptedFile),
    ],
)
def test_conversion_errors_are_mapped(tmp_path: Path, message: str, error: type[Exception]) -> None:
    class Failing:
        def convert(self, *_: Any, **__: Any) -> Any:
            raise RuntimeError(message)

    with pytest.raises(error):
        _parser(tmp_path, Failing()).parse(
            b"x", filename="f.pdf", detected=DetectedType.PDF, limits=ParseLimits()
        )


def test_rag_errors_from_prefilters_pass_through(tmp_path: Path) -> None:
    with pytest.raises(CorruptedFile):
        _parser(tmp_path, FakeConverter(_doc([]))).parse(
            b"nao e um docx", filename="f.docx", detected=DetectedType.DOCX, limits=ParseLimits()
        )


# ------------------------------------------------------------- INV-06 (pré e pós filtros)


def test_docx_and_html_are_prefiltered_before_conversion(tmp_path: Path) -> None:
    converter = FakeConverter(_doc([_item("TEXT", "ok")]))
    parser = _parser(tmp_path, converter)
    limits = ParseLimits()

    docx = parser.parse(
        corpus.read_bytes("A09"), filename="a09.docx", detected=DetectedType.DOCX, limits=limits
    )
    sent = converter.calls[-1][0][1]
    from docx import Document

    text = " ".join(p.text for p in Document(io.BytesIO(sent)).paragraphs)
    assert "HIDDEN-5521" not in text
    assert "receção" in text
    assert docx.warnings == ("hidden_text_removed",)

    html = parser.parse(
        corpus.read_bytes("A12"), filename="a12.html", detected=DetectedType.HTML, limits=limits
    )
    sent_html = converter.calls[-1][0][1].decode()
    assert "HIDDEN-HTML-3310" not in sent_html
    assert "<script" not in sent_html
    assert "20 lugares" in sent_html
    assert html.warnings == ("hidden_text_removed",)

    clean = parser.parse(
        b"<p>limpo</p>", filename="x.html", detected=DetectedType.HTML, limits=limits
    )
    assert clean.warnings == ()
    untouched = parser.parse(
        corpus.read_bytes("A02"), filename="a02.docx", detected=DetectedType.DOCX, limits=limits
    )
    assert untouched.warnings == ()
    assert converter.calls[-1][0][1] == corpus.read_bytes("A02")


def test_pdf_hidden_spans_are_removed_after_conversion(tmp_path: Path) -> None:
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, invariant=1)
    pdf.drawString(50, 780, "texto visível")
    pdf.setFillGray(1)
    pdf.drawString(50, 750, "HIDDEN-PDF-0007")
    pdf.showPage()
    pdf.save()
    converter = FakeConverter(
        _doc(
            [_item("TEXT", "texto visível HIDDEN-PDF-0007", 1), _item("TEXT", "HIDDEN-PDF-0007", 1)]
        )
    )
    doc = _parser(tmp_path, converter).parse(
        buf.getvalue(), filename="a.pdf", detected=DetectedType.PDF, limits=ParseLimits()
    )
    assert [b.text for b in doc.blocks] == ["texto visível"]
    assert doc.blocks[0].flags == {"hidden_text_removed"}
    assert doc.warnings == ("hidden_text_removed",)


# ------------------------------------------------------------------------- o registo


def test_full_registry_overrides_only_what_docling_supports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        docling_full, "_supported_types", lambda: frozenset({DetectedType.DOCX, DetectedType.PDF})
    )
    registry = full_registry(tmp_path)
    assert registry.profile == "full"
    assert registry.get(DetectedType.DOCX).name == "full-docling"
    assert registry.get(DetectedType.PDF).name == "full-docling"
    assert registry.get(DetectedType.EML).name == "lite-eml"  # anexos via parser lite
    assert registry.get(DetectedType.TXT).name == "lite-text"
    with pytest.raises(UnsupportedType):
        registry.get(DetectedType.MSG)


# ---------------------------------------------------------------- Docling real (docling)


@pytest.mark.docling
def test_inv06_full_profile_removes_hidden_text() -> None:
    from rag_core.parsing.docling_full import full_registry as real_registry

    registry = real_registry(corpus.CORPUS_DIR.parents[1] / ".docling-artifacts")
    for doc_id, canary in (("A09", "HIDDEN-5521"), ("A12", "HIDDEN-HTML-3310")):
        name = corpus.source_file_for(doc_id).filename
        detected = DetectedType.DOCX if name.endswith("docx") else DetectedType.HTML
        parsed = registry.get(detected).parse(
            corpus.read_bytes(doc_id), filename=name, detected=detected, limits=ParseLimits()
        )
        assert registry.get(detected).name == "full-docling"
        assert canary not in " ".join(b.text for b in parsed.blocks)
        assert "0000" not in " ".join(b.text for b in parsed.blocks)


@pytest.mark.docling
def test_inv06_full_profile_removes_white_pdf_text() -> None:
    from rag_core.parsing.docling_full import full_registry as real_registry

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, invariant=1)
    pdf.drawString(50, 780, "Texto visível do documento de teste para o Docling.")
    pdf.setFillGray(1)
    pdf.drawString(50, 700, "HIDDEN-PDF-0042")
    pdf.showPage()
    pdf.save()
    registry = real_registry(corpus.CORPUS_DIR.parents[1] / ".docling-artifacts")
    parsed = registry.get(DetectedType.PDF).parse(
        buf.getvalue(), filename="b.pdf", detected=DetectedType.PDF, limits=ParseLimits()
    )
    text = " ".join(b.text for b in parsed.blocks)
    assert "HIDDEN-PDF-0042" not in text
    assert "visível" in text


@pytest.mark.docling
def test_no_network_during_conversion() -> None:
    """Corre com o pytest-socket ativo (``--disable-socket``): qualquer ligação falharia."""
    import socket

    from rag_core.parsing.docling_full import full_registry as real_registry

    with pytest.raises(socket.error if False else Exception):
        socket.create_connection(("example.com", 80), timeout=1)
    registry = real_registry(corpus.CORPUS_DIR.parents[1] / ".docling-artifacts")
    parsed = registry.get(DetectedType.DOCX).parse(
        corpus.read_bytes("A02"),
        filename="a02.docx",
        detected=DetectedType.DOCX,
        limits=ParseLimits(),
    )
    assert parsed.blocks


def test_rag_errors_raised_by_the_converter_pass_through(tmp_path: Path) -> None:
    class Rejecting:
        def convert(self, *_: Any, **__: Any) -> Any:
            raise ValidationFailed(subcode="too_many_pages")

    with pytest.raises(ValidationFailed) as exc:
        _parser(tmp_path, Rejecting()).parse(
            b"x", filename="f.pdf", detected=DetectedType.PDF, limits=ParseLimits()
        )
    assert exc.value.subcode == "too_many_pages"
