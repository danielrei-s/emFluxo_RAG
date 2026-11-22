"""Registo do perfil lite: todos os parsers leves (sem Docling)."""

from __future__ import annotations

from rag_core.parsing.docx_lite import DocxParser
from rag_core.parsing.eml import EmlParser
from rag_core.parsing.html import HtmlParser
from rag_core.parsing.image import ImageParser
from rag_core.parsing.ocr import OcrEngine
from rag_core.parsing.pdf_lite import PdfParser
from rag_core.parsing.pptx_lite import PptxParser
from rag_core.parsing.registry import ParserRegistry
from rag_core.parsing.text import TextParser
from rag_core.parsing.xlsx_lite import XlsxParser


def lite_registry(ocr_engine: OcrEngine | None = None) -> ParserRegistry:
    """Registo com os parsers lite; ``ocr_engine`` ativa o OCR em PDFs digitalizados e imagens."""
    registry = ParserRegistry("lite")
    for parser in (
        TextParser(),
        HtmlParser(),
        DocxParser(),
        XlsxParser(),
        PptxParser(),
        PdfParser(ocr_engine),
        EmlParser(),
        ImageParser(ocr_engine),
    ):
        registry.register(parser)
    return registry
