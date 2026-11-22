"""Parser HTML: texto visível apenas; remove scripts e conteúdo oculto (F3-T03, INV-06)."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment, Doctype, Tag
from bs4.element import NavigableString

from rag_core.interfaces import ParseLimits
from rag_core.parsing.base import PARSER_VERSION, markdown_table
from rag_core.types import Block, DetectedType, StructuredDocument

HIDDEN_FLAG = "hidden_text_removed"
_DROPPED = frozenset({"script", "style", "noscript", "template", "iframe", "head"})
_HEADINGS = {f"h{n}": n for n in range(1, 7)}
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.IGNORECASE)
_SPACES = re.compile(r"\s+")


def _is_hidden(tag: Tag) -> bool:
    style = tag.get("style")
    return (
        tag.has_attr("hidden")
        or str(tag.get("aria-hidden", "")).lower() == "true"
        or (isinstance(style, str) and bool(_HIDDEN_STYLE.search(style)))
    )


class _Walker:
    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self.pending_hidden = False
        self.hidden_seen = False

    def _hide(self) -> None:
        self.pending_hidden = True
        self.hidden_seen = True

    def text_of(self, node: Tag) -> str:
        parts: list[str] = []
        for child in node.children:
            if isinstance(child, Tag):
                if child.name in _DROPPED:
                    continue
                if _is_hidden(child):
                    self._hide()
                    continue
                parts.append(" " if child.name == "br" else self.text_of(child))
            elif isinstance(child, NavigableString) and not isinstance(child, Comment | Doctype):
                parts.append(str(child))
        return _SPACES.sub(" ", "".join(parts)).strip()

    def emit(self, block: Block) -> None:
        if self.pending_hidden:
            block = block.model_copy(update={"flags": block.flags | {HIDDEN_FLAG}})
            self.pending_hidden = False
        self.blocks.append(block)

    def flag_trailing_hidden(self) -> None:
        """Conteúdo oculto sem bloco a seguir marca o último bloco."""
        if self.pending_hidden and self.blocks:
            last = self.blocks[-1]
            self.blocks[-1] = last.model_copy(update={"flags": last.flags | {HIDDEN_FLAG}})
        self.pending_hidden = False

    def table(self, node: Tag) -> None:
        rows = []
        for tr in node.find_all("tr"):
            cells = tuple(self.text_of(c) for c in tr.find_all(["th", "td"], recursive=False))
            if any(cells):
                rows.append(cells)
        if rows:
            self.emit(Block(kind="table", text=markdown_table(rows), rows=tuple(rows)))

    def visit(self, node: Tag) -> None:
        loose: list[str] = []

        def flush() -> None:
            text = _SPACES.sub(" ", " ".join(loose)).strip()
            loose.clear()
            if text:
                self.emit(Block(kind="paragraph", text=text))

        for child in node.children:
            if isinstance(child, Tag):
                if child.name in _DROPPED:
                    continue
                if _is_hidden(child):
                    self._hide()
                elif child.name in _HEADINGS or child.name in {"p", "li", "table"}:
                    flush()
                    self._block(child)
                elif child.name in {"div", "section", "article", "main", "body", "html", "ul",
                                    "ol", "header", "footer", "nav", "blockquote", "pre",
                                    "form", "aside", "figure"}:  # fmt: skip
                    flush()
                    self.visit(child)
                else:
                    loose.append(self.text_of(child))
            elif isinstance(child, NavigableString) and not isinstance(child, Comment | Doctype):
                loose.append(str(child))
        flush()

    def _block(self, tag: Tag) -> None:
        if tag.name == "table":
            self.table(tag)
            return
        text = self.text_of(tag)
        if not text:
            return
        if tag.name in _HEADINGS:
            self.emit(Block(kind="heading", text=text, level=_HEADINGS[tag.name]))
        else:
            if tag.name == "li":
                self.emit(Block(kind="list_item", text=text))
            else:
                self.emit(Block(kind="paragraph", text=text))


class HtmlParser:
    """HTML com ``html.parser``: headings, parágrafos, listas e tabelas do texto visível."""

    name = "lite-html"
    version = PARSER_VERSION
    supported = frozenset({DetectedType.HTML})

    def parse(
        self, data: bytes, *, filename: str, detected: DetectedType, limits: ParseLimits
    ) -> StructuredDocument:
        soup = BeautifulSoup(data, "html.parser")
        walker = _Walker()
        walker.visit(soup)
        walker.flag_trailing_hidden()
        title_tag = soup.find("title")
        title = _SPACES.sub(" ", title_tag.get_text()).strip() if title_tag else ""
        if not title:
            title = next(
                (b.text for b in walker.blocks if b.kind == "heading" and b.level == 1), ""
            )
        return StructuredDocument(
            title=title or None,
            detected_type=detected,
            blocks=tuple(walker.blocks),
            parser_name=self.name,
            parser_version=self.version,
            warnings=(HIDDEN_FLAG,) if walker.hidden_seen else (),
        )
