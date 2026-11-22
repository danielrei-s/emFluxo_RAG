"""Utilitários comuns dos parsers (F3-T03). Os parsers recebem ``bytes``, nunca caminhos."""

from __future__ import annotations

import re
from collections.abc import Sequence

PARSER_VERSION = "lite-1"
HIDDEN_FLAG = "hidden_text_removed"  # flag do bloco e aviso do documento (INV-06)


def _cell(value: str) -> str:
    return re.sub(r"\s*\n\s*", " ", value.strip()).replace("|", "\\|")


def markdown_table(rows: Sequence[Sequence[str]]) -> str:
    """Tabela markdown; 1.ª linha = cabeçalho; ``|`` é escapado, quebras de linha viram espaço."""
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    lines = [
        "| " + " | ".join(_cell(c) for c in (*row, *[""] * (width - len(row)))) + " |"
        for row in rows
    ]
    lines.insert(1, "| " + " | ".join(["---"] * width) + " |")
    return "\n".join(lines)


def split_paragraphs(text: str) -> list[str]:
    """Parágrafos separados por linhas em branco; quebras simples dentro deles viram espaço."""
    paragraphs: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip():
            current.append(line.strip())
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def decode_text(data: bytes) -> str:
    """UTF-8 (com ou sem BOM) com recurso a cp1252."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")
