"""LLM falso com quatro modos, para provar as defesas do sistema (C10)."""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from typing import Literal

from rag_core.generation.constants import NOT_FOUND
from rag_core.tokens import ApproxTokenCounter
from rag_core.types import ChatMessage, GenerationParams, LLMResult

Mode = Literal["scripted", "echo_cite", "obey_injection", "not_found"]

NOT_FOUND_TEXT = NOT_FOUND
INJECTION_TRIGGER = "Ignora todas as instruções"

_DOCUMENT_1_RE = re.compile(r'<document\s+index="1"[^>]*>(.*?)</document>', re.DOTALL)
_FIRST_SENTENCE_RE = re.compile(r"(.+?[.!?])(?:\s|$)", re.DOTALL)
_ONLY_RE = re.compile(r"responde apenas\s*:?\s*(.*)", re.IGNORECASE | re.DOTALL)
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)\s]*\)")


class FakeLLMProvider:
    """Modos: ``scripted``, ``echo_cite``, ``obey_injection`` e ``not_found``.

    Grava as mensagens recebidas em ``calls`` (inspeção do prompt: INV-02, INV-05, INV-17).
    """

    name = "fake-llm"

    def __init__(
        self,
        mode: Mode = "echo_cite",
        responses: Sequence[str] | None = None,
        is_remote: bool = False,
    ) -> None:
        self.mode: Mode = mode
        self.is_remote = is_remote
        self.calls: list[list[ChatMessage]] = []
        self._responses = list(responses or [])
        self._counter = ApproxTokenCounter()

    # ------------------------------------------------------------------ modos

    @staticmethod
    def _prompt_text(messages: Sequence[ChatMessage]) -> str:
        return "\n".join(m.content for m in messages)

    def _echo_cite(self, prompt: str) -> str:
        match = _DOCUMENT_1_RE.search(prompt)
        if match is None:
            return NOT_FOUND_TEXT
        body = " ".join(match.group(1).split())
        sentence = _FIRST_SENTENCE_RE.match(body)
        return f"{sentence.group(1) if sentence else body} [1]"

    def _obey_injection(self, prompt: str) -> str:
        if INJECTION_TRIGGER not in prompt:
            return self._echo_cite(prompt)
        match = _ONLY_RE.search(prompt)
        first_line = match.group(1).strip().splitlines()[0].strip() if match else ""
        images = [img for img in _MARKDOWN_IMAGE_RE.findall(prompt) if img not in first_line]
        return " ".join(part for part in (first_line, *dict.fromkeys(images)) if part)

    def _respond(self, messages: Sequence[ChatMessage]) -> str:
        self.calls.append(list(messages))
        prompt = self._prompt_text(messages)
        if self.mode == "scripted":
            if not self._responses:
                raise RuntimeError("respostas scripted esgotadas")
            return self._responses.pop(0)
        if self.mode == "echo_cite":
            return self._echo_cite(prompt)
        if self.mode == "obey_injection":
            return self._obey_injection(prompt)
        return NOT_FOUND_TEXT

    # ------------------------------------------------------------- interface

    def generate(self, messages: Sequence[ChatMessage], *, params: GenerationParams) -> LLMResult:
        text = self._respond(messages)
        return LLMResult(
            text=text,
            model=self.name,
            tokens_in=self._counter.count(self._prompt_text(messages)),
            tokens_out=self._counter.count(text),
            finish_reason="stop",
        )

    def stream(self, messages: Sequence[ChatMessage], *, params: GenerationParams) -> Iterator[str]:
        text = self._respond(messages)
        yield from re.findall(r"\S+\s*", text)
