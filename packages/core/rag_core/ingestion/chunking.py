"""Chunker estrutural (F3-T11): cortes por secção, com limites de tokens, tabelas e sobreposição."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rag_core.config import ChunkingSettings
from rag_core.interfaces import TokenCounter
from rag_core.parsing.base import markdown_table
from rag_core.types import Block, StructuredDocument

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True)
class ChunkDraft:
    """Chunk ainda sem identidade nem metadados de acesso."""

    ordinal: int
    text: str
    heading_path: tuple[str, ...] = ()
    page_start: int | None = None
    page_end: int | None = None
    flags: frozenset[str] = frozenset()


def embedding_text(draft: ChunkDraft) -> str:
    """Texto a embeber: o caminho de títulos, duas quebras de linha e o texto do chunk."""
    if not draft.heading_path:
        return draft.text
    return " > ".join(draft.heading_path) + "\n\n" + draft.text


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_BREAK.split(text) if s.strip()]


def _hard_cut(text: str, max_tokens: int, counter: TokenCounter) -> list[str]:
    """Corta por caracteres até cada parte caber em ``max_tokens``."""
    pieces: list[str] = []
    while text:
        size = max(1, len(text) * max_tokens // max(counter.count(text), 1))
        piece = text[:size]
        while len(piece) > 1 and counter.count(piece) > max_tokens:
            piece = piece[: max(1, len(piece) * 3 // 4)]
        pieces.append(piece)
        text = text[len(piece) :]
    return pieces


def _split_text(text: str, max_tokens: int, counter: TokenCounter) -> list[str]:
    """Parte um texto grande em pedaços ≤ ``max_tokens``: por frases e, no limite, por letras."""
    pieces: list[str] = []
    current = ""
    for sentence in _sentences(text):
        if counter.count(sentence) > max_tokens:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_hard_cut(sentence, max_tokens, counter))
            continue
        candidate = f"{current} {sentence}" if current else sentence
        if counter.count(candidate) > max_tokens:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


@dataclass
class _Builder:
    """Acumula os blocos do chunk em construção."""

    text: str = ""
    path: tuple[str, ...] = ()
    pages: list[int] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)
    carried: bool = False  # começa com texto de sobreposição

    def add(
        self, sep: str, text: str, block: Block, path: tuple[str, ...], *, first: bool = False
    ) -> None:
        self.text = text if not self.text else f"{self.text}{sep}{text}"
        if first or not self.path:
            self.path = path
        self.flags |= block.flags
        if block.page is not None:
            self.pages.append(block.page)


class _Chunker:
    def __init__(self, settings: ChunkingSettings, counter: TokenCounter) -> None:
        self.cfg = settings
        self.counter = counter
        self.drafts: list[ChunkDraft] = []
        self.stack: list[tuple[int, str]] = []
        self.current = _Builder()
        self.own_content = False  # o chunk em construção tem conteúdo que não é só sobreposição
        self.last_unit_kind = ""

    # ------------------------------------------------------------------ utilitários

    def _path(self) -> tuple[str, ...]:
        return tuple(title for _, title in self.stack)

    def _tokens(self, text: str) -> int:
        return self.counter.count(text)

    def _emit(self) -> None:
        """Fecha o chunk em construção (só se tiver conteúdo próprio, não só sobreposição)."""
        b = self.current
        text = b.text
        if self.own_content and text.strip():
            self.drafts.append(
                ChunkDraft(
                    ordinal=len(self.drafts),
                    text=text,
                    heading_path=b.path,
                    page_start=min(b.pages) if b.pages else None,
                    page_end=max(b.pages) if b.pages else None,
                    flags=frozenset(b.flags),
                )
            )
        self.current = _Builder()
        self.own_content = False
        self.last_unit_kind = ""

    def _overlap_for(self, previous_text: str) -> str:
        budget = int(self.cfg.overlap_ratio * self.cfg.target_tokens)
        tail: list[str] = []
        for sentence in reversed(_sentences(previous_text)):
            if self._tokens(" ".join([sentence, *tail])) > budget:
                break
            tail.insert(0, sentence)
        return " ".join(tail)

    def _close(self, *, overlap: bool) -> None:
        previous = self.current.text if self.own_content else ""
        self._emit()
        if overlap and previous:
            carried = self._overlap_for(previous)
            if carried:
                self.current.text = carried
                self.current.carried = True

    # ------------------------------------------------------------------ blocos

    def _add_unit(self, text: str, block: Block, kind: str, sep: str | None = None) -> None:
        if sep is None:
            list_continues = kind == "list_item" and self.last_unit_kind == "list_item"
            sep = "\n" if list_continues else "\n\n"
        candidate = text if not self.current.text else f"{self.current.text}{sep}{text}"
        if self._tokens(candidate) > self.cfg.max_tokens:
            self._close(overlap=True)
            candidate = f"{self.current.text}{sep}{text}" if self.current.text else text
            if self._tokens(candidate) > self.cfg.max_tokens:  # a sobreposição não cabe
                self.current = _Builder()
        first = not self.own_content
        self.current.add(sep, text, block, self._path(), first=first)
        self.own_content = True
        self.last_unit_kind = kind

    def text_block(self, block: Block) -> None:
        text = block.text.strip()
        if not text:
            return
        if self._tokens(text) <= self.cfg.max_tokens:
            self._add_unit(text, block, block.kind)
            return
        # parágrafo grande: frase a frase (a sobreposição precisa de unidades pequenas)
        pieces: list[str] = []
        for sentence in _sentences(text):
            if self._tokens(sentence) <= self.cfg.max_tokens:
                pieces.append(sentence)
            else:
                pieces.extend(_hard_cut(sentence, self.cfg.max_tokens, self.counter))
        for index, piece in enumerate(pieces):
            self._add_unit(piece, block, block.kind, sep=None if index == 0 else " ")

    def heading(self, block: Block) -> None:
        if self.own_content and self._tokens(self.current.text) >= self.cfg.min_tokens:
            self._close(overlap=False)
        level = block.level or 1
        while self.stack and self.stack[-1][0] >= level:
            self.stack.pop()
        title = block.text.strip()
        if title:
            self.stack.append((level, title))

    def table(self, block: Block) -> None:
        self._close(overlap=False)
        path = self._path()
        rows = block.rows
        if not rows or self._tokens(block.text) <= self.cfg.max_tokens:
            self._standalone(block.text, block, path)
            return
        header, body = rows[0], rows[1:]
        part: list[tuple[str, ...]] = []
        for row in body:
            candidate = markdown_table((header, *part, row))
            if part and self._tokens(candidate) > self.cfg.max_tokens:
                self._standalone(markdown_table((header, *part)), block, path)
                part = []
                candidate = markdown_table((header, row))
            if self._tokens(candidate) > self.cfg.max_tokens:  # linha enorme: corta por caracteres
                for piece in _split_text(
                    markdown_table((header, row)), self.cfg.max_tokens, self.counter
                ):
                    self._standalone(piece, block, path)
                continue
            part.append(row)
        if part:
            self._standalone(markdown_table((header, *part)), block, path)

    def _standalone(self, text: str, block: Block, path: tuple[str, ...]) -> None:
        pieces = (
            [text]
            if self._tokens(text) <= self.cfg.max_tokens
            else _split_text(text, self.cfg.max_tokens, self.counter)
        )
        for piece in pieces:
            self.current = _Builder()
            self.current.add("\n\n", piece, block, path, first=True)
            self.own_content = True
            self._emit()

    def run(self, doc: StructuredDocument) -> list[ChunkDraft]:
        for block in doc.blocks:
            if block.kind == "heading":
                self.heading(block)
            elif block.kind == "table":
                self.table(block)
            else:
                self.text_block(block)
        self._emit()
        return self.drafts


def chunk_document(
    doc: StructuredDocument, *, settings: ChunkingSettings, counter: TokenCounter
) -> list[ChunkDraft]:
    """Corta o documento em chunks de até ``max_tokens``, por secções (determinístico)."""
    return _Chunker(settings, counter).run(doc)
