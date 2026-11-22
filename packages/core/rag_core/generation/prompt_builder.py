"""Construtor do prompt (F4-T03): sistema, histórico, excertos delimitados e escapados.

INV-06: o conteúdo recuperado é dado, delimitado em ``<document>`` e escapado.
INV-17: só a pergunta e os melhores excertos seguem para o LLM, dentro do orçamento de tokens.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rag_core.config import Settings
from rag_core.generation.constants import GENERAL_KNOWLEDGE_MARKER, NOT_FOUND
from rag_core.interfaces import TenantPolicy, TokenCounter
from rag_core.types import ChatMessage, Chunk, SearchHit

SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "system_pt.md"
_VERSION_HEADER = re.compile(r"\A<!--.*?-->\s*", re.DOTALL)
_BLOCK = re.compile(r"\{\{#(\w+)\}\}\n(.*?)\{\{/\1\}\}\n", re.DOTALL)


@dataclass(frozen=True)
class PromptBundle:
    """Mensagens a enviar ao LLM e os excertos numerados que lá estão."""

    messages: list[ChatMessage]
    numbered: list[tuple[int, Chunk]]
    prompt_tokens: int


@lru_cache(maxsize=1)
def _system_template() -> str:
    return _VERSION_HEADER.sub("", SYSTEM_PROMPT_PATH.read_text(encoding="utf-8"))


def render_system_prompt(policy: TenantPolicy, sentinel: str) -> str:
    """Prompt de sistema com a variante da política de conhecimento geral e o sentinela."""
    template = _system_template()

    def keep_block(match: re.Match[str]) -> str:
        return match.group(2) if match.group(1) == policy.general_knowledge else ""

    text = _BLOCK.sub(keep_block, template)
    return (
        text.replace("{{NOT_FOUND}}", NOT_FOUND)
        .replace("{{GENERAL_KNOWLEDGE_MARKER}}", GENERAL_KNOWLEDGE_MARKER)
        .replace("{{SENTINEL}}", sentinel)
        .strip()
    )


def escape_markup(text: str, *, attribute: bool = False) -> str:
    """Escapa ``&``, ``<`` e ``>`` (e aspas, dentro de atributos)."""
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return escaped.replace('"', "&quot;") if attribute else escaped


def _pages(chunk: Chunk) -> str | None:
    start, end = chunk.metadata.page_start, chunk.metadata.page_end
    if start is None:
        return None
    return str(start) if end in (None, start) else f"{start}-{end}"


def format_document(index: int, chunk: Chunk) -> str:
    """``<document index="N" title="…" page="…">texto</document>`` com tudo escapado."""
    title = chunk.metadata.title or chunk.metadata.source_uri.rsplit("/", 1)[-1]
    attributes = f'index="{index}" title="{escape_markup(title, attribute=True)}"'
    pages = _pages(chunk)
    if pages:
        attributes += f' page="{pages}"'
    return f"<document {attributes}>{escape_markup(chunk.text)}</document>"


def build_messages(
    question: str,
    hits: Sequence[SearchHit],
    history: Sequence[ChatMessage],
    *,
    policy: TenantPolicy,
    settings: Settings,
    counter: TokenCounter,
    sentinel: str,
) -> PromptBundle:
    """Monta o prompt: sistema, histórico (últimas mensagens), excertos e pergunta."""
    budget = policy.max_prompt_tokens
    system = ChatMessage(role="system", content=render_system_prompt(policy, sentinel))
    question_line = f"Pergunta: {question}"
    used = counter.count(system.content) + counter.count(question_line)

    limit = settings.limits.max_history_messages
    recent = list(history)[-limit:] if limit else []
    kept_history: list[ChatMessage] = []
    for message in reversed(recent):  # as mais recentes têm prioridade
        cost = counter.count(message.content)
        if used + cost > budget:
            break
        kept_history.insert(0, message)
        used += cost

    documents: list[str] = []
    numbered: list[tuple[int, Chunk]] = []
    for hit in hits:
        number = len(numbered) + 1
        block = format_document(number, hit.chunk)
        cost = counter.count(block) + 1  # a quebra de linha
        if used + cost > budget:
            break  # os de menor score caem primeiro
        documents.append(block)
        numbered.append((number, hit.chunk))
        used += cost

    while True:
        user_content = "\n".join([*documents, question_line])
        messages = [system, *kept_history, ChatMessage(role="user", content=user_content)]
        prompt_tokens = sum(counter.count(m.content) for m in messages)
        if prompt_tokens <= budget or not documents:
            break
        documents.pop()  # arredondamentos da contagem: larga o excerto de menor score
        numbered.pop()
    return PromptBundle(messages=messages, numbered=numbered, prompt_tokens=prompt_tokens)
