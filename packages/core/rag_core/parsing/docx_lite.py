"""Parser DOCX do perfil lite (F3-T04): ordem do documento, títulos, listas, tabelas, sem oculto."""

from __future__ import annotations

import io
import re
from typing import Any

from docx import Document
from docx.shared import Pt, RGBColor
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from rag_core.errors import CorruptedFile, UnsupportedType
from rag_core.interfaces import ParseLimits
from rag_core.parsing.base import HIDDEN_FLAG, PARSER_VERSION, markdown_table
from rag_core.types import Block, DetectedType, StructuredDocument

_HEADING_STYLE = re.compile(r"^(?:heading|título|titulo)\s*(\d)$", re.IGNORECASE)
_TITLE_STYLES = frozenset({"title", "título", "titulo"})
_SPACES = re.compile(r"\s+")
_WHITE = RGBColor(0xFF, 0xFF, 0xFF)
_MIN_VISIBLE_SIZE = Pt(2)


def _is_hidden_run(run: Run) -> bool:
    font = run.font
    color = font.color.rgb if font.color is not None else None
    return (
        bool(font.hidden)
        or color == _WHITE
        or (font.size is not None and font.size < _MIN_VISIBLE_SIZE)
    )


def _visible_text(paragraph: Paragraph) -> tuple[str, bool]:
    """Texto visível do parágrafo e se algum run oculto foi removido."""
    parts: list[str] = []
    hidden = False
    for element in paragraph._p.xpath(".//w:r"):
        run = Run(element, paragraph)
        if _is_hidden_run(run):
            hidden = hidden or bool(run.text.strip())
        else:
            parts.append(run.text)
    return _SPACES.sub(" ", "".join(parts)).strip(), hidden


def _outline_level(paragraph: Paragraph) -> int | None:
    style = paragraph.style
    owners = [paragraph._p, *([style.element] if style is not None else [])]
    for owner in owners:
        values = owner.xpath("./w:pPr/w:outlineLvl/@w:val")
        if values:
            return min(int(values[0]) + 1, 6)
    return None


def _has_numbering(paragraph: Paragraph) -> bool:
    if paragraph._p.xpath("./w:pPr/w:numPr"):
        return True
    style = paragraph.style
    return style is not None and bool(style.element.xpath("./w:pPr/w:numPr"))


def strip_hidden_runs(data: bytes) -> tuple[bytes, bool]:
    """Remove do DOCX os runs ocultos (para parsers de terceiros). Devolve ``(bytes, mudou)``."""
    try:
        document = Document(io.BytesIO(data))
        removed = False
        for element in list(document.element.body.xpath(".//w:r")):
            run = Run(element, document)
            if _is_hidden_run(run) and run.text.strip():
                element.getparent().remove(element)
                removed = True
        if not removed:
            return data, False
        buffer = io.BytesIO()
        document.save(buffer)
        return buffer.getvalue(), True
    except Exception as exc:  # python-docx levanta tipos variados em ficheiros corrompidos
        raise CorruptedFile("docx_unreadable") from exc


class _Collector:
    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self.title: str | None = None
        self.pending_hidden = False
        self.hidden_seen = False

    def emit(self, block: Block, *, hidden: bool = False) -> None:
        if hidden or self.pending_hidden:
            block = block.model_copy(update={"flags": block.flags | {HIDDEN_FLAG}})
            self.pending_hidden = False
        self.blocks.append(block)

    def paragraph(self, paragraph: Paragraph) -> None:
        text, hidden = _visible_text(paragraph)
        self.hidden_seen = self.hidden_seen or hidden
        if not text:
            self.pending_hidden = self.pending_hidden or hidden
            return
        style_name = paragraph.style.name if paragraph.style is not None else ""
        style_name = style_name or ""
        match = _HEADING_STYLE.match(style_name.strip())
        if style_name.strip().lower() in _TITLE_STYLES:
            self.title = self.title or text
            self.emit(Block(kind="heading", text=text, level=1), hidden=hidden)
        elif match or (level := _outline_level(paragraph)) is not None:
            level = min(int(match.group(1)), 6) if match else (level or 1)
            self.emit(Block(kind="heading", text=text, level=max(level, 1)), hidden=hidden)
        elif _has_numbering(paragraph) or style_name.startswith("List"):
            self.emit(Block(kind="list_item", text=text), hidden=hidden)
        else:
            self.emit(Block(kind="paragraph", text=text), hidden=hidden)

    def table(self, table: Table) -> None:
        rows: list[tuple[str, ...]] = []
        hidden = False
        for row in table.rows:
            cells: list[str] = []
            previous: Any = None
            for cell in row.cells:
                if cell._tc is previous:  # célula fundida na horizontal
                    continue
                previous = cell._tc
                texts = []
                for paragraph in cell.paragraphs:
                    text, was_hidden = _visible_text(paragraph)
                    hidden = hidden or was_hidden
                    if text:
                        texts.append(text)
                cells.append(" ".join(texts))
            if any(cells):
                rows.append(tuple(cells))
        self.hidden_seen = self.hidden_seen or hidden
        if rows:
            self.emit(
                Block(kind="table", text=markdown_table(rows), rows=tuple(rows)), hidden=hidden
            )
        else:
            self.pending_hidden = self.pending_hidden or hidden

    def finish(self) -> None:
        """Conteúdo oculto sem bloco a seguir marca o último bloco."""
        if self.pending_hidden and self.blocks:
            last = self.blocks[-1]
            self.blocks[-1] = last.model_copy(update={"flags": last.flags | {HIDDEN_FLAG}})
        self.pending_hidden = False
        if self.title is None:
            self.title = next(
                (b.text for b in self.blocks if b.kind == "heading" and b.level == 1), None
            )


class DocxParser:
    """DOCX com ``python-docx``: a ordem entre parágrafos e tabelas é a do ficheiro."""

    name = "lite-docx"
    version = PARSER_VERSION
    supported = frozenset({DetectedType.DOCX})

    def parse(
        self, data: bytes, *, filename: str, detected: DetectedType, limits: ParseLimits
    ) -> StructuredDocument:
        if detected not in self.supported:
            raise UnsupportedType(f"docx_parser:{detected.value}")
        try:
            document = Document(io.BytesIO(data))
            collector = _Collector()
            for child in document.element.body.iterchildren():
                if child.tag.endswith("}p"):
                    collector.paragraph(Paragraph(child, document))
                elif child.tag.endswith("}tbl"):
                    collector.table(Table(child, document))
        except Exception as exc:  # python-docx levanta tipos variados em ficheiros corrompidos
            raise CorruptedFile("docx_unreadable") from exc
        collector.finish()
        return StructuredDocument(
            title=collector.title,
            detected_type=detected,
            blocks=tuple(collector.blocks),
            parser_name=self.name,
            parser_version=self.version,
            warnings=(HIDDEN_FLAG,) if collector.hidden_seen else (),
        )
