"""Localização de PII em texto (F4-T07): só valores que passam na validação."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from rag_core.pii.validators import valid_cc, valid_iban, valid_nif, valid_niss

_FLAGS = re.ASCII
_NIF = re.compile(r"(?<![0-9A-Za-z])[0-9]{9}(?![0-9A-Za-z])", _FLAGS)
_NISS = re.compile(r"(?<![0-9A-Za-z])[12][0-9]{10}(?![0-9A-Za-z])", _FLAGS)
_CC = re.compile(
    r"(?<![0-9A-Za-z])[0-9]{8}[ -]?[0-9][ -]?[A-Za-z0-9]{2}[0-9](?![0-9A-Za-z])", _FLAGS
)
_IBAN = re.compile(r"(?<![0-9A-Za-z])[A-Z]{2}[0-9]{2}(?: ?[A-Z0-9]){11,30}(?![0-9A-Za-z])", _FLAGS)
_EMAIL = re.compile(
    r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}", _FLAGS
)
_PHONE = re.compile(
    r"(?<![0-9A-Za-z+])(?:(?:\+|00)351[ -]?)?(?:9[1236]|2[0-9])(?:[ -]?[0-9]){7}(?![0-9A-Za-z])",
    _FLAGS,
)
# Em empate de tamanho, os identificadores com dígito de controlo ganham ao telefone.
KIND_PRIORITY = ("IBAN", "EMAIL", "CC", "NISS", "NIF", "TELEFONE")


@dataclass(frozen=True)
class PiiSpan:
    kind: str
    start: int
    end: int
    value: str


def _iban_spans(text: str) -> list[PiiSpan]:
    spans: list[PiiSpan] = []
    for match in _IBAN.finditer(text):
        raw = match.group(0)
        for end in range(len(raw), 14, -1):  # o resto da frase pode ter sido apanhado: encurta
            candidate = raw[:end].rstrip()
            if valid_iban(candidate):
                spans.append(
                    PiiSpan("IBAN", match.start(), match.start() + len(candidate), candidate)
                )
                break
    return spans


def _validated(
    kind: str, pattern: re.Pattern[str], text: str, check: Callable[[str], bool] | None = None
) -> list[PiiSpan]:
    spans = []
    for match in pattern.finditer(text):
        value = match.group(0)
        if check is None or check(value):
            spans.append(PiiSpan(kind, match.start(), match.end(), value))
    return spans


def find_pii(text: str) -> list[PiiSpan]:
    """PII validada, sem sobreposições (o maior ganha; em empate, ``KIND_PRIORITY``)."""
    candidates = [
        *_iban_spans(text),
        *_validated("EMAIL", _EMAIL, text),
        *_validated("CC", _CC, text, lambda v: valid_cc(re.sub(r"[ -]", "", v))),
        *_validated("NISS", _NISS, text, valid_niss),
        *_validated("NIF", _NIF, text, valid_nif),
        *_validated("TELEFONE", _PHONE, text),
    ]
    candidates.sort(key=lambda s: (-(s.end - s.start), KIND_PRIORITY.index(s.kind), s.start))
    chosen: list[PiiSpan] = []
    for span in candidates:
        if all(span.end <= c.start or span.start >= c.end for c in chosen):
            chosen.append(span)
    return sorted(chosen, key=lambda s: s.start)
