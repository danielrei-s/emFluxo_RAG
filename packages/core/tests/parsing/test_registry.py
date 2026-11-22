"""Testes de F3-T03: registo de parsers."""

from __future__ import annotations

import pytest
from rag_core.errors import UnsupportedType
from rag_core.interfaces import ParseLimits
from rag_core.parsing.html import HtmlParser
from rag_core.parsing.registry import ParserRegistry
from rag_core.parsing.text import TextParser
from rag_core.types import DetectedType, StructuredDocument


class _Override:
    name = "override"
    version = "9"
    supported = frozenset({DetectedType.TXT})

    def parse(
        self, data: bytes, *, filename: str, detected: DetectedType, limits: ParseLimits
    ) -> StructuredDocument:
        return StructuredDocument(
            detected_type=detected, blocks=(), parser_name=self.name, parser_version=self.version
        )


def test_registry_returns_registered_parser() -> None:
    registry = ParserRegistry("lite")
    text, html = TextParser(), HtmlParser()
    registry.register(text)
    registry.register(html)
    assert registry.profile == "lite"
    assert registry.get(DetectedType.CSV) is text
    assert registry.get(DetectedType.HTML) is html


def test_registry_later_registration_wins() -> None:
    registry = ParserRegistry("full")
    registry.register(TextParser())
    override = _Override()
    registry.register(override)
    assert registry.get(DetectedType.TXT) is override
    assert registry.get(DetectedType.MD).name == TextParser().name


def test_registry_unsupported_type_raises() -> None:
    registry = ParserRegistry("lite")
    registry.register(TextParser())
    with pytest.raises(UnsupportedType):
        registry.get(DetectedType.PDF)
    with pytest.raises(UnsupportedType):
        ParserRegistry("lite").get(DetectedType.TXT)
