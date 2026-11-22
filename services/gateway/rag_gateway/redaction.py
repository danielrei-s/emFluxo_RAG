"""Redação de PII para fornecedores externos (F6-T06; INV-05, INV-17).

Defesa em profundidade: o texto que sai para um fornecedor ``is_remote`` leva marcadores
(``[NIF_1]``) no lugar da PII, e a resposta é reidratada antes de voltar ao cliente.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from rag_core.generation.streaming import RehydratingStream
from rag_core.interfaces import LLMProvider
from rag_core.pii import Redactor
from rag_core.types import ChatMessage, GenerationParams, LLMResult


class RedactingProvider:
    """Embrulha um fornecedor para um único pedido; o ``Redactor`` é partilhado pelos fallbacks."""

    def __init__(self, inner: LLMProvider, redactor: Redactor) -> None:
        self._inner = inner
        self._redactor = redactor
        self.name = inner.name
        self.is_remote = inner.is_remote

    def _redacted(self, messages: Sequence[ChatMessage]) -> list[ChatMessage]:
        return [
            m.model_copy(update={"content": self._redactor.redact(m.content)}) for m in messages
        ]

    def generate(self, messages: Sequence[ChatMessage], *, params: GenerationParams) -> LLMResult:
        result = self._inner.generate(self._redacted(messages), params=params)
        return result.model_copy(update={"text": self._redactor.rehydrate(result.text)})

    def stream(self, messages: Sequence[ChatMessage], *, params: GenerationParams) -> Iterator[str]:
        rehydrating = RehydratingStream(self._redactor)
        for piece in self._inner.stream(self._redacted(messages), params=params):
            text = rehydrating.feed(piece)
            if text:
                yield text
        tail = rehydrating.flush()
        if tail:
            yield tail


def protect(provider: LLMProvider, redactor: Redactor | None) -> LLMProvider:
    """Só os fornecedores externos são embrulhados; os internos recebem o texto original."""
    if redactor is None or not provider.is_remote:
        return provider
    return RedactingProvider(provider, redactor)
