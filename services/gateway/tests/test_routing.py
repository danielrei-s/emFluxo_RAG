"""Testes de F6-T04: escolha de modelo, fallback e disjuntor."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime

import pytest
from rag_core.clock import FakeClock
from rag_core.errors import AccessDenied, UpstreamError
from rag_core.fakes import FakeLLMProvider
from rag_core.interfaces import TenantPolicy
from rag_core.types import ChatMessage, GenerationParams, LLMResult
from rag_gateway.routing import CircuitBreaker, ModelRouter

# O TestClient usa um par de sockets internos (loopback); nada sai da máquina.
pytestmark = pytest.mark.enable_socket
MESSAGES = [ChatMessage(role="user", content="olá")]
PARAMS = GenerationParams()
POLICY = TenantPolicy(tenant_id="t1", allowed_models=("primary", "secondary", "third"))
START = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)


class Failing:
    """Fornecedor que falha sempre (como um 500 ou um timeout)."""

    name = "failing"
    is_remote = False

    def __init__(self, detail: str = "http_500") -> None:
        self.detail = detail
        self.calls = 0

    def generate(self, messages: Sequence[ChatMessage], *, params: GenerationParams) -> LLMResult:
        self.calls += 1
        raise UpstreamError(self.detail)

    def stream(self, messages: Sequence[ChatMessage], *, params: GenerationParams) -> Iterator[str]:
        self.calls += 1
        raise UpstreamError(self.detail)
        yield ""  # pragma: no cover - torna a função um gerador


class Interrupted(FakeLLMProvider):
    """Dá um pedaço e depois falha (queda a meio do fluxo)."""

    def stream(self, messages: Sequence[ChatMessage], *, params: GenerationParams) -> Iterator[str]:
        yield "parcial "
        raise UpstreamError("stream_interrupted")


def _ok(text: str) -> FakeLLMProvider:
    return FakeLLMProvider("scripted", responses=[text] * 20)


def _router(**providers: object) -> tuple[ModelRouter, FakeClock]:
    clock = FakeClock(START)
    return ModelRouter(providers, clock), clock  # type: ignore[arg-type]


def test_primary_ok() -> None:
    router, _ = _router(primary=_ok("do primário"), secondary=_ok("do secundário"))
    routed = router.generate(None, POLICY, MESSAGES, PARAMS)
    assert (routed.alias, routed.result.text, routed.skipped) == ("primary", "do primário", ())
    chosen = router.generate("secondary", POLICY, MESSAGES, PARAMS)  # o cliente pede um alias
    assert (chosen.alias, chosen.result.text) == ("secondary", "do secundário")


def test_primary_500_falls_back() -> None:
    failing = Failing()
    router, _ = _router(primary=failing, secondary=_ok("do secundário"))
    routed = router.generate(None, POLICY, MESSAGES, PARAMS)
    assert (routed.alias, routed.result.text) == ("secondary", "do secundário")
    assert routed.skipped == ("primary",) and failing.calls == 1
    # um alias pedido que falha também cai para os restantes permitidos
    again = router.generate("secondary", POLICY, MESSAGES, PARAMS)
    assert again.alias == "secondary" and again.skipped == ()


def test_all_fail_502_problem() -> None:
    router, _ = _router(primary=Failing("timeout"), secondary=Failing(), third=Failing())
    with pytest.raises(UpstreamError) as exc:
        router.generate(None, POLICY, MESSAGES, PARAMS)
    assert exc.value.detail_id == "all_models_failed"

    from fastapi.testclient import TestClient
    from rag_core.config import Settings
    from rag_gateway.app import create_app

    app = create_app(Settings.for_tests())

    @app.get("/chat")
    def chat() -> None:
        router.generate(None, POLICY, MESSAGES, PARAMS)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/chat")
    assert response.status_code == 502
    assert response.json()["code"] == "upstream_error"
    assert response.json()["subcode"] == "all_models_failed"


def test_breaker_opens_and_skips() -> None:
    failing = Failing()
    router, clock = _router(primary=failing, secondary=_ok("ok"))
    for _ in range(3):  # 3 falhas seguidas abrem o disjuntor
        assert router.generate(None, POLICY, MESSAGES, PARAMS).alias == "secondary"
    assert failing.calls == 3
    routed = router.generate(None, POLICY, MESSAGES, PARAMS)
    assert routed.alias == "secondary" and routed.skipped == ("primary",)
    assert failing.calls == 3  # com o disjuntor aberto, o primário nem é chamado
    clock.advance(29)
    router.generate(None, POLICY, MESSAGES, PARAMS)
    assert failing.calls == 3
    clock.advance(2)  # passaram 30 s: deixa passar um pedido de teste
    router.generate(None, POLICY, MESSAGES, PARAMS)
    assert failing.calls == 4
    router.generate(None, POLICY, MESSAGES, PARAMS)  # a falha do teste voltou a abrir
    assert failing.calls == 4


def test_breaker_closes_after_a_success_and_counts_only_consecutive_failures() -> None:
    clock = FakeClock(START)
    breaker = CircuitBreaker(clock)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()  # a sequência foi interrompida
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.allow() is True
    breaker.record_failure()
    assert breaker.allow() is False
    clock.advance(30)
    assert breaker.allow() is True  # meio aberto
    breaker.record_success()
    breaker.record_failure()
    assert breaker.allow() is True  # voltou a contar do zero


def test_disallowed_model_403() -> None:
    router, _ = _router(primary=_ok("x"), forbidden=_ok("y"))
    with pytest.raises(AccessDenied) as exc:
        router.generate(
            "forbidden", POLICY, MESSAGES, PARAMS
        )  # existe mas a política não o permite
    assert exc.value.detail_id == "model_not_allowed"
    with pytest.raises(AccessDenied):
        router.generate("nao-existe", POLICY, MESSAGES, PARAMS)
    only_primary = TenantPolicy(tenant_id="t1", allowed_models=("primary",))
    assert router.generate(None, only_primary, MESSAGES, PARAMS).alias == "primary"


def test_aliases_without_a_provider_are_skipped() -> None:
    router, _ = _router(secondary=_ok("só este"))  # "primary" e "third" não têm fornecedor
    routed = router.generate(None, POLICY, MESSAGES, PARAMS)
    assert (routed.alias, routed.skipped) == ("secondary", ("primary",))


def test_stream_falls_back_only_before_the_first_token() -> None:
    router, _ = _router(primary=Failing(), secondary=_ok("palavra um dois"))
    pieces = list(router.stream(None, POLICY, MESSAGES, PARAMS))
    assert {alias for alias, _ in pieces} == {"secondary"}
    assert "".join(text for _, text in pieces) == "palavra um dois"

    mid, _ = _router(
        primary=Interrupted("scripted", responses=[]), secondary=_ok("não devia ser usado")
    )
    stream = mid.stream(None, POLICY, MESSAGES, PARAMS)
    assert next(stream) == ("primary", "parcial ")
    with pytest.raises(UpstreamError) as exc:  # a meio do fluxo já não se muda de modelo
        next(stream)
    assert exc.value.detail_id == "stream_interrupted"

    dead, _ = _router(primary=Failing(), secondary=Failing())
    with pytest.raises(UpstreamError) as all_failed:
        list(dead.stream(None, POLICY, MESSAGES, PARAMS))
    assert all_failed.value.detail_id == "all_models_failed"
    silent, _ = _router(primary=FakeLLMProvider("scripted", responses=[""]))
    assert (
        list(
            silent.stream(
                None, TenantPolicy(tenant_id="t", allowed_models=("primary",)), MESSAGES, PARAMS
            )
        )
        == []
    )
