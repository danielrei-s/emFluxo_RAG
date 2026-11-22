"""Testes de F4-T08: streaming do serviço de conversa e reidratação segura."""

from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st
from rag_core.clock import FakeClock
from rag_core.config import RetrievalSettings, Settings
from rag_core.fakes import FakeEmbedder, FakeLLMProvider, FakeReranker, InMemoryVectorStore
from rag_core.generation import ChatService, RehydratingStream
from rag_core.generation.constants import NOT_FOUND
from rag_core.generation.streaming import MAX_PENDING_CHARS
from rag_core.interfaces import TenantPolicy
from rag_core.pii import Redactor
from rag_core.retrieval import HybridRetriever
from rag_core.testing import corpus
from rag_core.types import Answer, Origin

TENANT = corpus.tenant_id("aurora")
POLICY = TenantPolicy(tenant_id=TENANT)
PARTIAL = re.compile(r"\[[A-Z_0-9]*$")


def _events(store: InMemoryVectorStore, llm: FakeLLMProvider, question: str) -> list[dict]:  # type: ignore[type-arg]
    settings = Settings.for_tests(retrieval=RetrievalSettings(min_relevance=0.05))
    service = ChatService(
        HybridRetriever(store, FakeEmbedder(), settings),
        FakeReranker(),
        llm,
        settings,
        FakeClock(),
        "SENTINELA-STREAM",
    )
    stream = service.stream_answer(
        question,
        [],
        corpus.principal_for("aurora", "ana"),
        policy=POLICY,
        origins=frozenset({Origin.CENTRAL}),
    )
    return list(stream)  # type: ignore[arg-type]


def _final(events: list[dict]) -> Answer:  # type: ignore[type-arg]
    return events[-1]["answer"]  # type: ignore[no-any-return]


def test_stream_events_order_and_replace_on_invalid(indexed_store: InMemoryVectorStore) -> None:
    good = FakeLLMProvider("scripted", responses=["Tem 25 dias úteis de férias por ano [1]."])
    events = _events(indexed_store, good, "Quantos dias de férias tenho por ano?")
    assert events[0]["type"] == "meta"
    assert events[-1]["type"] == "final"
    assert all(e["type"] == "token" for e in events[1:-1])
    assert events[0]["used_chunk_ids"]
    assert "".join(e["text"] for e in events[1:-1]).strip() == _final(events).text
    assert events[-1]["replace"] is False
    assert _final(events).kind == "grounded"
    assert len(good.calls) == 1  # sem repetição durante o streaming

    bad = FakeLLMProvider("scripted", responses=["Resposta inventada sem nenhuma fonte."])
    events = _events(indexed_store, bad, "Quantos dias de férias tenho por ano?")
    assert "".join(e["text"] for e in events[1:-1]) == "Resposta inventada sem nenhuma fonte."
    final = events[-1]
    assert final["replace"] is True
    assert (final["answer"].kind, final["answer"].text) == ("not_found", NOT_FOUND)
    assert final["answer"].warnings[0] == "citation_validation_failed"
    assert len(bad.calls) == 1


def test_stream_replaces_when_output_filter_changes_the_text(
    indexed_store: InMemoryVectorStore,
) -> None:
    llm = FakeLLMProvider(
        "scripted", responses=["Campanha em setembro [1] ![x](https://exfil.example/c)"]
    )
    events = _events(indexed_store, llm, "Resume a campanha de regresso às aulas em setembro.")
    streamed = "".join(e["text"] for e in events[1:-1])
    assert "exfil.example" in streamed  # já seguiu: a UI sanitiza e o final substitui
    assert events[-1]["replace"] is True
    assert "exfil.example" not in _final(events).text


def test_stream_with_redaction_never_leaks_placeholders(indexed_store: InMemoryVectorStore) -> None:
    llm = FakeLLMProvider(
        "scripted",
        responses=["O NIF da empresa é [NIF_1] [1] e o email [EMAIL_1]."],
        is_remote=True,
    )
    events = _events(indexed_store, llm, "Qual é o NIF da empresa e o email do DPO?")
    tokens = [e["text"] for e in events[1:-1]]
    assert all(not PARTIAL.search(t) for t in tokens)
    assert not any("[NIF_" in t or "[EMAIL_" in t for t in tokens)
    streamed = "".join(tokens)
    assert "123456789" in streamed and "dpo@aurora.example" in streamed
    assert _final(events).text == streamed.strip()
    assert events[-1]["replace"] is False


def test_rehydrating_stream_never_emits_partial_placeholder() -> None:
    redactor = Redactor()
    redactor.redact("NIF 123456789 e email a@b.example")
    stream = RehydratingStream(redactor)
    pieces = ["O NIF é [NI", "F_1] e o ", "email [EMAIL", "_1", "] fim [", "1] ok"]
    out = [stream.feed(p) for p in pieces]
    out.append(stream.flush())
    assert "".join(out) == "O NIF é 123456789 e o email a@b.example fim [1] ok"
    assert all(not PARTIAL.search(piece) for piece in out)
    assert out[0] == "O NIF é "  # o "[NI" ficou retido


def test_rehydrating_stream_edge_cases() -> None:
    plain = RehydratingStream(None)
    assert plain.feed("[NIF_") == "[NIF_"  # sem redator não há nada a reter
    assert plain.flush() == ""

    stream = RehydratingStream(Redactor())
    assert stream.feed("texto [ABCDEFGHIJKLMNOPQRSTUV") == "texto [ABCDEFGHIJKLMNOPQRSTUV"
    assert stream.feed("fim [NIF_9]") == "fim [NIF_9]"  # marcador desconhecido fica como está
    assert stream.feed("fica [TELE") == "fica "
    assert stream.flush() == "[TELE"  # no fim, o retido sai
    assert len("[TELEFONE_999]") <= MAX_PENDING_CHARS


@settings(max_examples=200, deadline=None)
@given(
    st.lists(
        st.sampled_from(["[NIF_1]", "[EMAIL_1]", "[1]", "texto ", "[", "]", "NIF_", "é ", "[X"]),
        max_size=12,
    ),
    st.lists(st.integers(1, 6), min_size=1, max_size=8),
)
def test_rehydrating_stream_matches_whole_text(parts: list[str], sizes: list[int]) -> None:
    redactor = Redactor()
    redactor.redact("123456789 a@b.example")
    text = "".join(parts)
    stream = RehydratingStream(redactor)
    out, position, i = [], 0, 0
    while position < len(text):
        step = sizes[i % len(sizes)]
        out.append(stream.feed(text[position : position + step]))
        position += step
        i += 1
    out.append(stream.flush())
    assert "".join(out) == redactor.rehydrate(text)


def test_stream_flushes_a_pending_fragment_at_the_end(indexed_store: InMemoryVectorStore) -> None:
    llm = FakeLLMProvider("scripted", responses=["Tem 25 dias [1] mais [TELE"], is_remote=True)
    events = _events(indexed_store, llm, "Quantos dias de férias tenho por ano?")
    tokens = [e["text"] for e in events if e["type"] == "token"]
    assert tokens[-1] == "[TELE"  # retido durante o fluxo e libertado no fim
    assert _final(events).text.endswith("[TELE")
