"""Orquestrador de conversa (F4-T08): pesquisa, filtros, redação, LLM, validação e saída."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime

from rag_core.config import Settings
from rag_core.generation.answer_policy import answer_from_text, finalize, not_found_fallback
from rag_core.generation.output_filter import sanitize_answer_markdown
from rag_core.generation.prompt_builder import PromptBundle, build_messages
from rag_core.generation.query import retrieval_query, signal_injection, validate_question
from rag_core.generation.streaming import ChatEvent, RehydratingStream
from rag_core.interfaces import Clock, LLMProvider, Reranker, TenantPolicy
from rag_core.pii import Redactor
from rag_core.retrieval import HybridRetriever, select_context
from rag_core.tokens import ApproxTokenCounter
from rag_core.types import (
    AccessFilter,
    Answer,
    ChatMessage,
    GenerationParams,
    Origin,
    Principal,
    SearchHit,
    SentExcerpt,
)

LOCAL_ONLY_EXCLUDED = "local_only_excluded"
PII_REDACTED = "pii_redacted"


@dataclass
class _Prepared:
    bundle: PromptBundle
    redactor: Redactor | None
    sent_excerpts: tuple[SentExcerpt, ...]
    warnings: tuple[str, ...]
    params: GenerationParams
    started: datetime
    retrieval_ms: int


class ChatService:
    """Junta recuperação, política de dados, prompt, LLM e validação (todos os produtos)."""

    def __init__(
        self,
        retriever: HybridRetriever,
        reranker: Reranker,
        llm: LLMProvider,
        settings: Settings,
        clock: Clock,
        sentinel: str,
        allowed_link_domains: Sequence[str] = (),
        destination_label: str = "",
    ) -> None:
        self._retriever = retriever
        self._reranker = reranker
        self._llm = llm
        self._settings = settings
        self._clock = clock
        self._sentinel = sentinel
        self._domains = tuple(allowed_link_domains)
        self._destination = destination_label or f"llm:{llm.name}"
        self._counter = ApproxTokenCounter()

    # ------------------------------------------------------------------ preparação

    def _ms_since(self, started: datetime) -> int:
        return int((self._clock.now() - started).total_seconds() * 1000)

    def _select(self, query: str, flt: AccessFilter) -> list[SearchHit]:
        hits = self._retriever.retrieve(query, flt)
        return select_context(query, hits, reranker=self._reranker, settings=self._settings)

    def _prepare(
        self,
        question: str,
        history: Sequence[ChatMessage],
        principal: Principal,
        policy: TenantPolicy,
        origins: frozenset[Origin],
    ) -> _Prepared:
        started = self._clock.now()
        question = validate_question(question, self._settings.limits)
        signal_injection(question)
        search_query = retrieval_query(question, history)

        remote = self._llm.is_remote
        guard = remote and Origin.LOCAL in origins  # só dados locais saem do dispositivo
        flt = AccessFilter.for_principal(
            principal,
            origins=origins,
            exclude_local_only=guard,
            exclude_classifications=policy.block_cloud_for if guard else frozenset(),
        )
        selected = self._select(search_query, flt)
        warnings: list[str] = []
        if guard:  # segunda pesquisa, sem exclusões, só para saber se algo ficou de fora
            open_flt = AccessFilter.for_principal(principal, origins=origins)
            if any(
                h.chunk.metadata.local_only
                or h.chunk.metadata.classification in policy.block_cloud_for
                for h in self._select(search_query, open_flt)
            ):
                warnings.append(LOCAL_ONLY_EXCLUDED)
        retrieval_ms = self._ms_since(started)

        redactor: Redactor | None = None
        sent: list[SentExcerpt] = []
        sent_question, sent_history = question, list(history)
        if remote and policy.redact_pii_for_external:
            redactor = Redactor()
            sent_question = redactor.redact(question)
            sent_history = [
                m.model_copy(update={"content": redactor.redact(m.content)}) for m in history
            ]
            redacted_hits = []
            for hit in selected:
                before = redactor.count
                text = redactor.redact(hit.chunk.text)
                redacted_hits.append(
                    hit.model_copy(update={"chunk": hit.chunk.model_copy(update={"text": text})})
                )
                sent.append(
                    SentExcerpt(
                        chunk_id=hit.chunk.chunk_id,
                        destination=self._destination,
                        text_sent=text,
                        redactions=redactor.count - before,
                    )
                )
            selected = redacted_hits
            if redactor.count:
                warnings.append(PII_REDACTED)
        elif remote:
            sent = [
                SentExcerpt(
                    chunk_id=h.chunk.chunk_id,
                    destination=self._destination,
                    text_sent=h.chunk.text,
                )
                for h in selected
            ]

        bundle = build_messages(
            sent_question,
            selected,
            sent_history,
            policy=policy,
            settings=self._settings,
            counter=self._counter,
            sentinel=self._sentinel,
        )
        in_prompt = {chunk.chunk_id for _, chunk in bundle.numbered}
        return _Prepared(
            bundle=bundle,
            redactor=redactor,
            sent_excerpts=tuple(s for s in sent if s.chunk_id in in_prompt),
            warnings=tuple(warnings),
            params=GenerationParams(max_tokens=policy.max_output_tokens),
            started=started,
            retrieval_ms=retrieval_ms,
        )

    def _finish(self, answer: Answer, prep: _Prepared, llm_ms: int) -> Answer:
        text = prep.redactor.rehydrate(answer.text) if prep.redactor else answer.text
        text = sanitize_answer_markdown(text, allowed_link_domains=self._domains)
        return answer.model_copy(
            update={
                "text": text,
                "sent_excerpts": prep.sent_excerpts,
                "warnings": (*answer.warnings, *prep.warnings),
                "timings_ms": {
                    "retrieval": prep.retrieval_ms,
                    "llm": llm_ms,
                    "total": self._ms_since(prep.started),
                },
            }
        )

    # --------------------------------------------------------------------- API

    def answer(
        self,
        question: str,
        history: Sequence[ChatMessage],
        principal: Principal,
        *,
        policy: TenantPolicy,
        origins: frozenset[Origin],
    ) -> Answer:
        """Resposta completa, validada e sanitizada."""
        prep = self._prepare(question, history, principal, policy, origins)
        llm_started = self._clock.now()
        answer = finalize(self._llm, prep.bundle, policy, prep.params, self._sentinel)
        return self._finish(answer, prep, self._ms_since(llm_started))

    def stream_answer(
        self,
        question: str,
        history: Sequence[ChatMessage],
        principal: Principal,
        *,
        policy: TenantPolicy,
        origins: frozenset[Origin],
    ) -> Iterator[ChatEvent]:
        """Eventos ``meta``, ``token``… e ``final`` (validação no fim, sem repetição)."""
        prep = self._prepare(question, history, principal, policy, origins)
        yield {"type": "meta", "used_chunk_ids": [c.chunk_id for _, c in prep.bundle.numbered]}
        llm_started = self._clock.now()
        stream = RehydratingStream(prep.redactor)
        raw: list[str] = []
        shown: list[str] = []
        for piece in self._llm.stream(prep.bundle.messages, params=prep.params):
            raw.append(piece)
            out = stream.feed(piece)
            if out:
                shown.append(out)
                yield {"type": "token", "text": out}
        tail = stream.flush()
        if tail:
            shown.append(tail)
            yield {"type": "token", "text": tail}
        valid = answer_from_text("".join(raw), self._llm.name, prep.bundle, policy, self._sentinel)
        final = self._finish(valid or not_found_fallback(), prep, self._ms_since(llm_started))
        yield {
            "type": "final",
            "answer": final,
            "replace": final.text != "".join(shown).strip(),
        }
