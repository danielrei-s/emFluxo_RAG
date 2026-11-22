"""Parser PDF do perfil lite (F3-T06): texto por página sem texto invisível; marca páginas OCR."""

from __future__ import annotations

import io
from collections.abc import Mapping
from typing import Any

import pdfplumber
import pypdfium2
from pdfminer.pdfdocument import PDFEncryptionError

from rag_core.errors import CorruptedFile, EncryptedFile, UnsupportedType, ValidationFailed
from rag_core.interfaces import ParseLimits
from rag_core.parsing.base import HIDDEN_FLAG, PARSER_VERSION
from rag_core.types import Block, DetectedType, StructuredDocument

NEEDS_OCR_FLAG = "needs_ocr"
MIN_PAGE_CHARS = 20
MIN_VISIBLE_SIZE = 1.0  # pt
PARAGRAPH_GAP = 0.75  # intervalo entre linhas, em alturas de linha, que separa parágrafos
_EPS = 1e-3


def _is_white(color: Any) -> bool:
    if isinstance(color, int | float):
        color = (color,)
    if not isinstance(color, tuple | list) or not all(isinstance(c, int | float) for c in color):
        return False
    if len(color) in (1, 3):  # cinzento ou RGB
        return all(c >= 1 - _EPS for c in color)
    return len(color) == 4 and all(c <= _EPS for c in color)  # CMYK


def is_hidden_char(obj: Mapping[str, Any]) -> bool:
    """Carácter invisível: preenchimento branco (RGB, cinzento, CMYK) ou tamanho < 1 pt."""
    if obj.get("object_type") != "char":
        return False
    size = obj.get("size")
    too_small = isinstance(size, int | float) and size < MIN_VISIBLE_SIZE
    return too_small or _is_white(obj.get("non_stroking_color"))


def _paragraphs(page: Any) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    previous: Mapping[str, Any] | None = None
    for line in page.extract_text_lines(return_chars=False):
        text = str(line["text"]).strip()
        if not text:
            continue
        if previous is not None:
            height = max(previous["bottom"] - previous["top"], 1.0)
            if line["top"] - previous["bottom"] > PARAGRAPH_GAP * height:
                paragraphs.append(" ".join(current))
                current = []
        current.append(text)
        previous = line
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def _headings_by_page(data: bytes) -> dict[int, list[tuple[int, str]]]:
    headings: dict[int, list[tuple[int, str]]] = {}
    try:
        document = pypdfium2.PdfDocument(data)
        try:
            for item in document.get_toc():
                dest = item.get_dest()
                index = dest.get_index() if dest is not None else None
                title = (item.get_title() or "").strip()
                if index is not None and title:
                    headings.setdefault(index + 1, []).append((min(item.level + 1, 6), title))
        finally:
            document.close()
    except Exception:  # índice ilegível não impede a extração do texto
        return {}
    return headings


def _open(data: bytes) -> Any:
    try:
        return pdfplumber.open(io.BytesIO(data))
    except Exception as exc:  # pdfminer levanta tipos variados em ficheiros corrompidos
        # o pdfplumber embrulha o erro original do pdfminer em PdfminerException
        if any(isinstance(e, PDFEncryptionError) for e in (exc, *exc.args)):
            raise EncryptedFile("pdf_password_required") from exc
        raise CorruptedFile("pdf_unreadable") from exc


def hidden_text_spans(data: bytes) -> list[str]:
    """Trechos de texto invisível (por página, caracteres contíguos); para o adaptador Docling."""
    spans: list[str] = []
    with _open(data) as pdf:
        for page in pdf.pages:
            run: list[str] = []
            for char in page.chars:
                if is_hidden_char(char):
                    run.append(char["text"])
                elif run:
                    spans.append("".join(run))
                    run = []
            if run:
                spans.append("".join(run))
    return [s.strip() for s in spans if s.strip()]


class PdfParser:
    """PDF com ``pdfplumber``; os bookmarks (via ``pypdfium2``) viram headings."""

    name = "lite-pdf"
    version = PARSER_VERSION
    supported = frozenset({DetectedType.PDF})

    def parse(
        self, data: bytes, *, filename: str, detected: DetectedType, limits: ParseLimits
    ) -> StructuredDocument:
        if detected not in self.supported:
            raise UnsupportedType(f"pdf_parser:{detected.value}")
        blocks: list[Block] = []
        hidden_seen = False
        headings = _headings_by_page(data)
        with _open(data) as pdf:
            page_count = len(pdf.pages)
            if page_count > limits.max_pages:
                raise ValidationFailed(subcode="too_many_pages")
            try:
                for number, page in enumerate(pdf.pages, start=1):
                    visible = page.filter(lambda o: not is_hidden_char(o))
                    removed = len(page.chars) - len(visible.chars)
                    flags = frozenset({HIDDEN_FLAG}) if removed else frozenset()
                    hidden_seen = hidden_seen or bool(removed)
                    for level, title in headings.get(number, []):
                        blocks.append(Block(kind="heading", text=title, level=level, page=number))
                    paragraphs = _paragraphs(visible)
                    if sum(len(p) for p in paragraphs) < MIN_PAGE_CHARS:
                        blocks.append(
                            Block(
                                kind="paragraph",
                                text="",
                                page=number,
                                flags=flags | {NEEDS_OCR_FLAG},
                            )
                        )
                        continue
                    blocks.extend(
                        Block(kind="paragraph", text=p, page=number, flags=flags)
                        for p in paragraphs
                    )
            except Exception as exc:  # erro de sintaxe a meio das páginas
                raise CorruptedFile("pdf_unreadable") from exc
        return StructuredDocument(
            detected_type=detected,
            blocks=tuple(blocks),
            page_count=page_count,
            parser_name=self.name,
            parser_version=self.version,
            warnings=(HIDDEN_FLAG,) if hidden_seen else (),
        )
