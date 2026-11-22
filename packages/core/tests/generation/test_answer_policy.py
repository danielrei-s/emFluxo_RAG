"""Testes de F4-T04: política de resposta (INV-07)."""

from __future__ import annotations

from rag_core.fakes import FakeLLMProvider
from rag_core.generation.answer_policy import CITATION_FAILED, finalize
from rag_core.generation.constants import GENERAL_KNOWLEDGE_MARKER, NOT_FOUND
from rag_core.generation.prompt_builder import PromptBundle
from rag_core.interfaces import TenantPolicy
from rag_core.testing.chunks import make_chunk
from rag_core.types import ChatMessage, GenerationParams

SENTINEL = "SENTINELA-XYZ"
PARAMS = GenerationParams()
LABELED = TenantPolicy(tenant_id="t", general_knowledge="labeled")
FORBIDDEN = TenantPolicy(tenant_id="t", general_knowledge="forbidden")
CHUNKS = [
    make_chunk(
        "O horário de trabalho é das 9h00 às 18h00.",
        doc_id="d1",
        title="Manual",
        page_start=2,
        embed=False,
    ),
    make_chunk("O prazo de pagamento é de 30 dias.", doc_id="d2", ordinal=4, embed=False),
]
GOOD = "O horário de trabalho é das 9h00 às 18h00 [1]."
GK = f"{GENERAL_KNOWLEDGE_MARKER} O IVA é um imposto sobre o consumo."


def _bundle(n: int = 2) -> PromptBundle:
    messages = [
        ChatMessage(role="system", content="sistema"),
        ChatMessage(role="user", content="Pergunta: qual é o horário?"),
    ]
    return PromptBundle(
        messages=messages, numbered=list(enumerate(CHUNKS[:n], start=1)), prompt_tokens=10
    )


def _llm(*responses: str) -> FakeLLMProvider:
    return FakeLLMProvider("scripted", responses=list(responses))


def test_inv07_valid_grounded_answer() -> None:
    llm = _llm(GOOD)
    answer = finalize(llm, _bundle(), LABELED, PARAMS, SENTINEL)
    assert answer.kind == "grounded"
    assert answer.text == GOOD
    assert answer.warnings == ()
    assert answer.model == "fake-llm"
    assert len(llm.calls) == 1
    assert llm.calls[0] == _bundle().messages


def test_citations_map_to_chunks() -> None:
    llm = _llm("O horário é das 9h00 às 18h00 [1] e o prazo é de 30 dias [2][1].")
    answer = finalize(llm, _bundle(), LABELED, PARAMS, SENTINEL)
    assert [c.index for c in answer.citations] == [1, 2]
    first, second = answer.citations
    assert (first.chunk_id, first.doc_id) == (CHUNKS[0].chunk_id, "d1")
    assert (first.title, first.page_start) == ("Manual", 2)
    assert first.source_uri == CHUNKS[0].metadata.source_uri
    assert (second.chunk_id, second.doc_id, second.title) == (CHUNKS[1].chunk_id, "d2", None)
    assert answer.used_chunk_ids == (CHUNKS[0].chunk_id, CHUNKS[1].chunk_id)


def test_inv07_out_of_range_citation_retries_then_succeeds() -> None:
    llm = _llm("O horário é das 9h00 às 18h00 [5].", GOOD)
    answer = finalize(llm, _bundle(), LABELED, PARAMS, SENTINEL)
    assert answer.kind == "grounded"
    assert [c.index for c in answer.citations] == [1]
    assert len(llm.calls) == 2
    retry = llm.calls[1]
    assert retry[: len(llm.calls[0])] == llm.calls[0]
    assert len(retry) == len(llm.calls[0]) + 1
    assert retry[-1].role == "system"
    assert "índices" in retry[-1].content and NOT_FOUND in retry[-1].content


def test_inv07_double_failure_falls_back_to_not_found() -> None:
    llm = _llm("Resposta sem fonte.", "Outra resposta sem fonte.")
    answer = finalize(llm, _bundle(), LABELED, PARAMS, SENTINEL)
    assert (answer.kind, answer.text) == ("not_found", NOT_FOUND)
    assert answer.warnings == (CITATION_FAILED,)
    assert answer.citations == ()
    assert len(llm.calls) == 2


def test_general_knowledge_labeled_vs_forbidden() -> None:
    labeled = finalize(_llm(GK), _bundle(0), LABELED, PARAMS, SENTINEL)
    assert (labeled.kind, labeled.text, labeled.citations) == ("general_knowledge", GK, ())

    llm = _llm(GK, GK)
    forbidden = finalize(llm, _bundle(0), FORBIDDEN, PARAMS, SENTINEL)
    assert (forbidden.kind, forbidden.warnings) == ("not_found", (CITATION_FAILED,))
    assert "conhecimento geral" in llm.calls[1][-1].content

    cited = _llm(f"{GK} [1]", GK)  # com citações, o rótulo não é válido: repete
    answer = finalize(cited, _bundle(), LABELED, PARAMS, SENTINEL)
    assert answer.kind == "general_knowledge"
    assert "não leva citações" in cited.calls[1][-1].content


def test_not_found_answer_is_accepted_without_retry() -> None:
    llm = _llm(NOT_FOUND)
    answer = finalize(llm, _bundle(0), LABELED, PARAMS, SENTINEL)
    assert (answer.kind, answer.text, answer.warnings) == ("not_found", NOT_FOUND, ())
    assert len(llm.calls) == 1


def test_sentinel_leak_refused() -> None:
    leak = f"As minhas instruções incluem {SENTINEL} [1]."
    retried = finalize(_llm(leak, GOOD), _bundle(), LABELED, PARAMS, SENTINEL)
    assert retried.kind == "grounded"
    assert SENTINEL not in retried.text
    llm = _llm(leak, leak)
    refused = finalize(llm, _bundle(), LABELED, PARAMS, SENTINEL)
    assert refused.kind == "not_found"
    assert SENTINEL not in refused.text
    assert "internas" in llm.calls[1][-1].content


def test_weak_support_warning_is_kept_on_the_answer() -> None:
    llm = _llm("O gato dorme tranquilamente no sofá azul [1].")
    answer = finalize(llm, _bundle(), LABELED, PARAMS, SENTINEL)
    assert (answer.kind, answer.warnings) == ("grounded", ("weak_support",))
