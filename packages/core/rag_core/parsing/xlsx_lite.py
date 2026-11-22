"""Parser XLSX do perfil lite (F3-T05): uma tabela por folha visível; folhas ocultas ignoradas."""

from __future__ import annotations

import io
from datetime import date, datetime, time
from typing import Any

from openpyxl import load_workbook

from rag_core.errors import CorruptedFile, UnsupportedType
from rag_core.interfaces import ParseLimits
from rag_core.parsing.base import PARSER_VERSION, markdown_table
from rag_core.types import Block, DetectedType, StructuredDocument

ROWS_PER_BLOCK = 50  # linhas de dados por bloco; o cabeçalho repete-se em cada um
HIDDEN_SHEET_FLAG = "hidden_sheet_skipped"
FORMULA_WARNING = "formula_without_cached_value"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        # o Excel guarda datas como datetime à meia-noite
        return (value.date() if value.time() == time(0) else value).isoformat()
    if isinstance(value, date | time):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _sheet_rows(values: Any, formulas: Any) -> tuple[list[tuple[str, ...]], bool]:
    """Linhas não vazias como texto (sem colunas vazias) e se há fórmulas sem valor em cache."""
    rows: list[list[str]] = []
    uncached = False
    for cached_row, formula_row in zip(values, formulas, strict=False):
        for cached, formula in zip(cached_row, formula_row, strict=False):
            if cached is None and isinstance(formula, str) and formula.startswith("="):
                uncached = True
        cells = [_text(c) for c in cached_row]
        if any(cells):
            rows.append(cells)
    width = max((len(r) for r in rows), default=0)
    padded = [r + [""] * (width - len(r)) for r in rows]
    keep = [i for i in range(width) if any(r[i] for r in padded)]
    return [tuple(r[i] for i in keep) for r in padded], uncached


class XlsxParser:
    """XLSX com ``openpyxl`` (só leitura, valores em cache): cada folha vira heading + tabelas."""

    name = "lite-xlsx"
    version = PARSER_VERSION
    supported = frozenset({DetectedType.XLSX})

    def parse(
        self, data: bytes, *, filename: str, detected: DetectedType, limits: ParseLimits
    ) -> StructuredDocument:
        if detected not in self.supported:
            raise UnsupportedType(f"xlsx_parser:{detected.value}")
        blocks: list[Block] = []
        warnings: list[str] = []
        pending_hidden = False
        try:
            cached = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            formulas = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
            try:
                for sheet in cached.worksheets:
                    if sheet.sheet_state != "visible":
                        pending_hidden = True
                        if HIDDEN_SHEET_FLAG not in warnings:
                            warnings.append(HIDDEN_SHEET_FLAG)
                        continue
                    rows, uncached = _sheet_rows(
                        sheet.iter_rows(values_only=True),
                        formulas[sheet.title].iter_rows(values_only=True),
                    )
                    if uncached and FORMULA_WARNING not in warnings:
                        warnings.append(FORMULA_WARNING)
                    if not rows:
                        continue
                    flags = frozenset({HIDDEN_SHEET_FLAG}) if pending_hidden else frozenset()
                    pending_hidden = False
                    blocks.append(Block(kind="heading", text=sheet.title, level=1, flags=flags))
                    header, body = rows[0], rows[1:]
                    for start in range(0, max(len(body), 1), ROWS_PER_BLOCK):
                        chunk = (header, *body[start : start + ROWS_PER_BLOCK])
                        blocks.append(Block(kind="table", text=markdown_table(chunk), rows=chunk))
            finally:
                cached.close()
                formulas.close()
        except Exception as exc:  # openpyxl levanta tipos variados em ficheiros corrompidos
            raise CorruptedFile("xlsx_unreadable") from exc
        if pending_hidden and blocks:
            last = blocks[-1]
            blocks[-1] = last.model_copy(update={"flags": last.flags | {HIDDEN_SHEET_FLAG}})
        return StructuredDocument(
            detected_type=detected,
            blocks=tuple(blocks),
            parser_name=self.name,
            parser_version=self.version,
            warnings=tuple(warnings),
        )
