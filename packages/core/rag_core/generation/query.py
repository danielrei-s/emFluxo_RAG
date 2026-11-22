"""Tratamento da pergunta: limites, condensação com histórico e sinalização (F4-T06)."""

from __future__ import annotations

import re
from collections.abc import Sequence

from rag_core.config import LimitsSettings
from rag_core.errors import ValidationFailed
from rag_core.ingestion.sanitize import detect_injection
from rag_core.interfaces import LLMProvider
from rag_core.logging import get_logger
from rag_core.types import ChatMessage, GenerationParams

SHORT_QUESTION_WORDS = 8
_ANAPHORA = re.compile(
    r"(?<!\w)(?:e o|e a|e os|e as|e no|e na|e nos|e nas|e para|isso|isto|esse|essa|esses|essas"
    r"|dele|dela|deles|delas|também)(?!\w)",
    re.IGNORECASE,
)
_CONDENSE_SYSTEM = (
    "Reescreve a última pergunta do utilizador numa única pergunta curta e autónoma, em "
    "português, usando o histórico só para resolver referências. Responde apenas com a pergunta."
)
CONDENSE_PARAMS = GenerationParams(max_tokens=80, temperature=0.0)


def validate_question(question: str, limits: LimitsSettings) -> str:
    """Devolve a pergunta sem espaços nas pontas; vazia ou demasiado longa levanta erro."""
    stripped = question.strip()
    if not stripped:
        raise ValidationFailed(subcode="empty_question")
    if len(stripped) > limits.max_question_chars:
        raise ValidationFailed(subcode="question_too_long")
    return stripped


def signal_injection(question: str) -> list[str]:
    """Regista (sem conteúdo) se a pergunta parece uma tentativa de injection; não bloqueia."""
    rules = detect_injection(question)
    if rules:
        get_logger("query").warning("query_injection_suspected", count=len(rules))
    return rules


def _needs_context(question: str) -> bool:
    return len(question.split()) < SHORT_QUESTION_WORDS or bool(_ANAPHORA.search(question))


def retrieval_query(
    question: str,
    history: Sequence[ChatMessage],
    *,
    llm: LLMProvider | None = None,
    use_llm: bool = False,
) -> str:
    """Pergunta a usar na pesquisa: com histórico, junta a última pergunta do utilizador."""
    previous = next((m.content for m in reversed(history) if m.role == "user"), None)
    if previous is None or not _needs_context(question):
        return question
    if use_llm and llm is not None:
        messages = [
            ChatMessage(role="system", content=_CONDENSE_SYSTEM),
            ChatMessage(role="user", content=f"Histórico: {previous}\nPergunta: {question}"),
        ]
        rewritten = llm.generate(messages, params=CONDENSE_PARAMS).text.strip()
        if rewritten:
            return rewritten
    return f"{previous} {question}"
