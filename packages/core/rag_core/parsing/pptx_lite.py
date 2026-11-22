"""Parser PPTX do perfil lite (F3-T05): diapositivos com título, texto, tabelas e notas."""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from typing import Any

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from rag_core.errors import CorruptedFile, UnsupportedType
from rag_core.interfaces import ParseLimits
from rag_core.parsing.base import PARSER_VERSION, markdown_table
from rag_core.types import Block, DetectedType, StructuredDocument

NOTES_FLAG = "speaker_notes"
_SPACES = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _SPACES.sub(" ", text).strip()  # inclui o \v (quebra de linha do PowerPoint)


def _walk(shapes: Any) -> Iterator[Any]:
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _walk(shape.shapes)
        else:
            yield shape


def _slide_blocks(slide: Any, number: int) -> tuple[list[Block], str | None]:
    title_shape = slide.shapes.title
    title = _clean(title_shape.text_frame.text) if title_shape is not None else ""
    heading = f"Diapositivo {number}: {title}" if title else f"Diapositivo {number}"
    blocks = [Block(kind="heading", text=heading, level=1, page=number)]
    for shape in _walk(slide.shapes):
        if title_shape is not None and shape.shape_id == title_shape.shape_id:
            continue
        if getattr(shape, "has_table", False) and shape.has_table:
            rows = tuple(tuple(_clean(cell.text) for cell in row.cells) for row in shape.table.rows)
            rows = tuple(r for r in rows if any(r))
            if rows:
                blocks.append(
                    Block(kind="table", text=markdown_table(rows), rows=rows, page=number)
                )
        elif shape.has_text_frame:
            for paragraph in shape.text_frame.paragraphs:
                if text := _clean(paragraph.text):
                    blocks.append(Block(kind="paragraph", text=text, page=number))
    if slide.has_notes_slide:
        for paragraph in slide.notes_slide.notes_text_frame.paragraphs:
            if text := _clean(paragraph.text):
                blocks.append(
                    Block(kind="paragraph", text=text, page=number, flags=frozenset({NOTES_FLAG}))
                )
    return blocks, title or None


class PptxParser:
    """PPTX com ``python-pptx``; ``page`` é o número do diapositivo."""

    name = "lite-pptx"
    version = PARSER_VERSION
    supported = frozenset({DetectedType.PPTX})

    def parse(
        self, data: bytes, *, filename: str, detected: DetectedType, limits: ParseLimits
    ) -> StructuredDocument:
        if detected not in self.supported:
            raise UnsupportedType(f"pptx_parser:{detected.value}")
        blocks: list[Block] = []
        doc_title: str | None = None
        try:
            presentation = Presentation(io.BytesIO(data))
            slides = list(presentation.slides)
            for number, slide in enumerate(slides, start=1):
                slide_blocks, title = _slide_blocks(slide, number)
                blocks.extend(slide_blocks)
                doc_title = doc_title or title
        except Exception as exc:  # python-pptx levanta tipos variados em ficheiros corrompidos
            raise CorruptedFile("pptx_unreadable") from exc
        return StructuredDocument(
            title=doc_title,
            detected_type=detected,
            blocks=tuple(blocks),
            page_count=len(slides),
            parser_name=self.name,
            parser_version=self.version,
        )
