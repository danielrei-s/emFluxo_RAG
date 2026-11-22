"""Redator de PII com reidratação (F4-T07, INV-05/INV-17): uma instância por pedido."""

from __future__ import annotations

import re

from rag_core.pii.recognizers import find_pii

_PLACEHOLDER = re.compile(r"\[(?:NIF|NISS|CC|IBAN|EMAIL|TELEFONE)_[0-9]+\]", re.ASCII)


class Redactor:
    """Troca PII por marcadores estáveis (``[NIF_1]``) e repõe-nos depois.

    O mesmo valor (exatamente a mesma string) recebe sempre o mesmo marcador em todos os textos
    do pedido. Texto já redigido não é redigido outra vez.
    """

    def __init__(self) -> None:
        self._placeholder_of: dict[tuple[str, str], str] = {}
        self._value_of: dict[str, str] = {}
        self._counters: dict[str, int] = {}
        self.count = 0

    def _placeholder(self, kind: str, value: str) -> str:
        key = (kind, value)
        if key not in self._placeholder_of:
            number = self._counters.get(kind, 0) + 1
            self._counters[kind] = number
            placeholder = f"[{kind}_{number}]"
            self._placeholder_of[key] = placeholder
            self._value_of[placeholder] = value
        return self._placeholder_of[key]

    def redact(self, text: str) -> str:
        """Devolve o texto com a PII validada substituída por marcadores."""
        pieces: list[str] = []
        cursor = 0
        for span in find_pii(text):
            pieces.append(text[cursor : span.start])
            pieces.append(self._placeholder(span.kind, span.value))
            cursor = span.end
            self.count += 1
        pieces.append(text[cursor:])
        return "".join(pieces)

    def rehydrate(self, text: str) -> str:
        """Repõe os valores originais; marcadores desconhecidos ficam como estão."""
        return _PLACEHOLDER.sub(lambda m: self._value_of.get(m.group(0), m.group(0)), text)
