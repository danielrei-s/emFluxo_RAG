"""Parser dos formatos de texto: TXT, MD e CSV (F3-T03)."""

from __future__ import annotations

import csv
import io
import re

from rag_core.errors import UnsupportedType
from rag_core.interfaces import ParseLimits
from rag_core.parsing.base import PARSER_VERSION, decode_text, markdown_table, split_paragraphs
from rag_core.types import Block, DetectedType, StructuredDocument

CSV_ROWS_PER_BLOCK = 50  # linhas de dados por bloco; o cabeçalho repete-se em cada um

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_TABLE_SEPARATOR = re.compile(r"^\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?$")


def _table_rows(lines: list[str]) -> tuple[tuple[str, ...], ...]:
    rows = []
    for line in lines:
        stripped = line.strip()
        if _TABLE_SEPARATOR.match(stripped):
            continue
        cells = stripped.removeprefix("|").removesuffix("|").split("|")
        rows.append(tuple(c.strip() for c in cells))
    return tuple(rows)


def _parse_md(text: str) -> tuple[list[Block], str | None]:
    blocks: list[Block] = []
    title: str | None = None
    paragraph: list[str] = []
    table: list[str] = []

    def flush() -> None:
        nonlocal paragraph, table
        if paragraph:
            blocks.append(Block(kind="paragraph", text=" ".join(paragraph)))
            paragraph = []
        if table:
            rows = _table_rows(table)
            blocks.append(Block(kind="table", text=markdown_table(rows), rows=rows))
            table = []

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            if paragraph:
                flush()
            table.append(stripped)
            continue
        if table:
            flush()
        heading = _HEADING.match(stripped)
        item = _LIST_ITEM.match(line)
        if not stripped:
            flush()
        elif heading:
            flush()
            level = len(heading.group(1))
            blocks.append(Block(kind="heading", text=heading.group(2), level=level))
            if level == 1 and title is None:
                title = heading.group(2)
        elif item:
            flush()
            blocks.append(Block(kind="list_item", text=item.group(1).strip()))
        else:
            paragraph.append(stripped)
    flush()
    return blocks, title


def _parse_csv(text: str) -> list[Block]:
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(text[:4096], ";,\t")
    except csv.Error:
        dialect = csv.excel
    rows = [tuple(r) for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if not rows:
        return []
    header, body = rows[0], rows[1:]
    chunks = [body[i : i + CSV_ROWS_PER_BLOCK] for i in range(0, len(body), CSV_ROWS_PER_BLOCK)]
    return [
        Block(kind="table", text=markdown_table((header, *chunk)), rows=(header, *chunk))
        for chunk in chunks or [[]]
    ]


class TextParser:
    """TXT: parágrafos; MD: headings, tabelas e listas; CSV: tabelas de até 50 linhas."""

    name = "lite-text"
    version = PARSER_VERSION
    supported = frozenset({DetectedType.TXT, DetectedType.MD, DetectedType.CSV})

    def parse(
        self, data: bytes, *, filename: str, detected: DetectedType, limits: ParseLimits
    ) -> StructuredDocument:
        if detected not in self.supported:
            raise UnsupportedType(f"text_parser:{detected.value}")
        text = decode_text(data)
        title: str | None = None
        if detected == DetectedType.MD:
            blocks, title = _parse_md(text)
        elif detected == DetectedType.CSV:
            blocks = _parse_csv(text)
        else:
            blocks = [Block(kind="paragraph", text=p) for p in split_paragraphs(text)]
        return StructuredDocument(
            title=title,
            detected_type=detected,
            blocks=tuple(blocks),
            parser_name=self.name,
            parser_version=self.version,
        )
