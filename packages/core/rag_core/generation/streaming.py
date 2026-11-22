"""Streaming com reidratação segura (F4-T08): nunca emite um marcador ``[…]`` a meio."""

from __future__ import annotations

import re
from typing import Literal, TypedDict

from rag_core.pii import Redactor
from rag_core.types import Answer

_PARTIAL_MARKER = re.compile(r"\[[A-Z_0-9]*$")
MAX_PENDING_CHARS = 16  # "[TELEFONE_999]" tem 14; acima disto já não é um marcador


class MetaEvent(TypedDict):
    type: Literal["meta"]
    used_chunk_ids: list[str]


class TokenEvent(TypedDict):
    type: Literal["token"]
    text: str


class FinalEvent(TypedDict):
    type: Literal["final"]
    answer: Answer
    replace: bool  # o texto final difere do que foi transmitido: o cliente tem de o substituir


ChatEvent = MetaEvent | TokenEvent | FinalEvent


class RehydratingStream:
    """Repõe a PII nos pedaços do LLM; guarda um marcador incompleto até ele fechar."""

    def __init__(self, redactor: Redactor | None) -> None:
        self._redactor = redactor
        self._pending = ""

    def _rehydrate(self, text: str) -> str:
        return self._redactor.rehydrate(text) if self._redactor else text

    def feed(self, chunk: str) -> str:
        """Devolve o texto já seguro para emitir (pode ser vazio)."""
        if self._redactor is None:
            return chunk
        buffer = self._pending + chunk
        match = _PARTIAL_MARKER.search(buffer)
        hold = match.start() if match and len(buffer) - match.start() <= MAX_PENDING_CHARS else None
        if hold is None:
            self._pending = ""
            return self._rehydrate(buffer)
        self._pending = buffer[hold:]
        return self._rehydrate(buffer[:hold])

    def flush(self) -> str:
        """No fim do fluxo liberta o que ficou retido."""
        pending, self._pending = self._pending, ""
        return self._rehydrate(pending)
