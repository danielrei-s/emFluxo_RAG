"""Adaptador Docling do perfil full, só na central (F3-T09).

Produz o mesmo ``StructuredDocument`` que o perfil lite. O Docling não filtra texto oculto, por
isso o DOCX e o HTML são pré-filtrados e, nos PDFs, as strings de ``hidden_text_spans`` são
removidas depois da conversão (INV-06). Sem downloads em runtime: os modelos vivem em
``artifacts_path`` (a imagem do serviço define ``HF_HUB_OFFLINE=1``; só o módulo de config lê o
ambiente). O EML fica no parser lite para que os anexos sigam como ``RawAttachment`` (ingestão
recursiva).
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rag_core.errors import CorruptedFile, EncryptedFile, UnsupportedType, ValidationFailed
from rag_core.ingestion.sanitize import clean_text
from rag_core.interfaces import ParseLimits
from rag_core.parsing.base import HIDDEN_FLAG, PARSER_VERSION, markdown_table
from rag_core.parsing.docx_lite import strip_hidden_runs
from rag_core.parsing.html import strip_hidden_html
from rag_core.parsing.lite import lite_registry
from rag_core.parsing.pdf_lite import hidden_text_spans
from rag_core.parsing.registry import ParserRegistry
from rag_core.types import Block, DetectedType, StructuredDocument

# DetectedType -> nome do membro de InputFormat do Docling (só entra o que o enum tiver).
_FORMAT_NAMES: dict[DetectedType, str] = {
    DetectedType.PDF: "PDF",
    DetectedType.DOCX: "DOCX",
    DetectedType.PPTX: "PPTX",
    DetectedType.XLSX: "XLSX",
    DetectedType.HTML: "HTML",
    DetectedType.MD: "MD",
    DetectedType.CSV: "CSV",
    DetectedType.PNG: "IMAGE",
    DetectedType.JPEG: "IMAGE",
    DetectedType.TIFF: "IMAGE",
}
_PARAGRAPH_LABELS = frozenset(
    {"TEXT", "PARAGRAPH", "CAPTION", "FOOTNOTE", "CODE", "FORMULA", "HANDWRITTEN_TEXT", "REFERENCE"}
)
_SPACES = re.compile(r"\s+")


def _supported_types() -> frozenset[DetectedType]:  # pragma: no cover - exige o extra docling
    from docling.datamodel.base_models import InputFormat

    return frozenset(t for t, name in _FORMAT_NAMES.items() if name in InputFormat.__members__)


def _build_converter(
    artifacts_path: Path, ocr: bool, timeout_s: float
) -> Any:  # pragma: no cover - exige o extra docling e os modelos
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

    options = PdfPipelineOptions(
        artifacts_path=str(artifacts_path),
        do_ocr=ocr,
        enable_remote_services=False,
        allow_external_plugins=False,
        document_timeout=timeout_s,
    )
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=options),
        }
    )


def _document_stream(name: str, data: bytes) -> Any:  # pragma: no cover - exige o extra docling
    from docling.datamodel.base_models import DocumentStream

    return DocumentStream(name=name, stream=io.BytesIO(data))


def _page_of(item: Any) -> int | None:
    provenance = getattr(item, "prov", None)
    return int(provenance[0].page_no) if provenance else None


def _table_rows(item: Any) -> tuple[tuple[str, ...], ...]:
    rows = (tuple(_SPACES.sub(" ", str(c.text)).strip() for c in row) for row in item.data.grid)
    return tuple(r for r in rows if any(r))


def map_document(doc: Any) -> tuple[list[Block], str | None, int | None]:
    """Converte um ``DoclingDocument`` em blocos (por ``duck typing``: só usa ``label.name``)."""
    blocks: list[Block] = []
    title: str | None = None
    for item, _ in doc.iterate_items():
        label = item.label.name
        page = _page_of(item)
        if label == "TABLE":
            rows = _table_rows(item)
            if rows:
                blocks.append(Block(kind="table", text=markdown_table(rows), rows=rows, page=page))
            continue
        text = _SPACES.sub(" ", str(getattr(item, "text", "") or "")).strip()
        if not text:
            continue
        if label == "TITLE":
            title = title or text
            blocks.append(Block(kind="heading", text=text, level=1, page=page))
        elif label == "SECTION_HEADER":
            level = min(max(int(getattr(item, "level", 1) or 1), 1), 6)
            blocks.append(Block(kind="heading", text=text, level=level, page=page))
        elif label == "LIST_ITEM":
            blocks.append(Block(kind="list_item", text=text, page=page))
        elif label == "PICTURE":
            blocks.append(Block(kind="image_text", text=text, page=page))
        elif label in _PARAGRAPH_LABELS:
            blocks.append(Block(kind="paragraph", text=text, page=page))
    pages = getattr(doc, "pages", None)
    return blocks, title, (len(pages) if pages else None)


def remove_hidden_spans(blocks: list[Block], spans: list[str]) -> tuple[list[Block], bool]:
    """Tira dos blocos as strings de texto invisível; blocos que ficam vazios desaparecem."""
    if not spans:
        return blocks, False
    result: list[Block] = []
    changed = False
    for block in blocks:
        text = block.text
        for span in sorted(set(spans), key=len, reverse=True):
            text = text.replace(span, " ")
        text = _SPACES.sub(" ", text).strip()
        if text != block.text:
            changed = True
            if not text:
                continue
            block = block.model_copy(
                update={"text": text, "flags": block.flags | {HIDDEN_FLAG}, "rows": None}
                if block.kind != "table"
                else {"flags": block.flags | {HIDDEN_FLAG}}
            )
        result.append(block)
    return result, changed


def _clean_blocks(blocks: list[Block]) -> list[Block]:
    cleaned: list[Block] = []
    for block in blocks:
        text = clean_text(block.text).text
        rows = (
            tuple(tuple(clean_text(c).text for c in row) for row in block.rows)
            if block.rows
            else block.rows
        )
        if text or rows:
            cleaned.append(block.model_copy(update={"text": text, "rows": rows}))
    return cleaned


class DoclingParser:
    """Docling para os formatos que o enum de formatos instalado suportar."""

    name = "full-docling"
    version = PARSER_VERSION

    def __init__(
        self,
        artifacts_path: Path,
        *,
        converter_factory: Callable[[Path, bool, float], Any] | None = None,
        supported: frozenset[DetectedType] | None = None,
    ) -> None:
        if not artifacts_path.is_dir():
            raise ValidationFailed(subcode="docling_artifacts_missing")
        self._artifacts = artifacts_path
        self._factory = converter_factory or _build_converter
        self.supported = supported if supported is not None else _supported_types()
        self._converters: dict[bool, Any] = {}

    def _converter(self, limits: ParseLimits) -> Any:
        if limits.ocr not in self._converters:
            self._converters[limits.ocr] = self._factory(
                self._artifacts, limits.ocr, limits.timeout_s
            )
        return self._converters[limits.ocr]

    def parse(
        self, data: bytes, *, filename: str, detected: DetectedType, limits: ParseLimits
    ) -> StructuredDocument:
        if detected not in self.supported:
            raise UnsupportedType(f"docling_parser:{detected.value}")
        hidden = False
        if detected == DetectedType.DOCX:
            data, hidden = strip_hidden_runs(data)
        elif detected == DetectedType.HTML:
            data, hidden = strip_hidden_html(data)
        try:
            result = self._converter(limits).convert(
                _document_stream(filename, data),
                max_num_pages=limits.max_pages,
                max_file_size=limits.max_bytes,
            )
            blocks, title, page_count = map_document(result.document)
        except (ValidationFailed, CorruptedFile):
            raise
        except Exception as exc:  # o Docling levanta ConversionError e erros dos backends
            message = str(exc).lower()
            if "password" in message or "encrypted" in message:
                raise EncryptedFile("docling_encrypted") from exc
            if "page" in message and ("exceed" in message or "limit" in message):
                raise ValidationFailed(subcode="too_many_pages") from exc
            raise CorruptedFile("docling_conversion_failed") from exc
        if detected == DetectedType.PDF:
            blocks, removed = remove_hidden_spans(blocks, hidden_text_spans(data))
            hidden = hidden or removed
        blocks = _clean_blocks(blocks)
        return StructuredDocument(
            title=clean_text(title).text if title else None,
            detected_type=detected,
            blocks=tuple(blocks),
            page_count=page_count,
            parser_name=self.name,
            parser_version=self.version,
            warnings=(HIDDEN_FLAG,) if hidden else (),
        )


def full_registry(artifacts_path: Path) -> ParserRegistry:
    """Perfil full: parsers lite como base e o Docling por cima dos formatos que ele suporta."""
    lite = lite_registry()
    registry = ParserRegistry("full")
    for detected in DetectedType:
        try:
            registry.register(lite.get(detected))
        except UnsupportedType:
            continue
    registry.register(DoclingParser(artifacts_path))
    return registry
