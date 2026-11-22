"""Registo de parsers por perfil (``lite`` ou ``full``)."""

from __future__ import annotations

from typing import Literal

from rag_core.errors import UnsupportedType
from rag_core.interfaces import Parser
from rag_core.types import DetectedType


class ParserRegistry:
    """Associa cada ``DetectedType`` ao parser que o trata; o último registo ganha."""

    def __init__(self, profile: Literal["lite", "full"]) -> None:
        self.profile = profile
        self._parsers: dict[DetectedType, Parser] = {}

    def register(self, parser: Parser) -> None:
        for detected in parser.supported:
            self._parsers[detected] = parser

    def get(self, detected: DetectedType) -> Parser:
        try:
            return self._parsers[detected]
        except KeyError:
            raise UnsupportedType(f"no_parser:{detected.value}") from None
