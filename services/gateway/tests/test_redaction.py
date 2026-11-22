"""Testes de F6-T06: redação de PII para fornecedores externos (INV-05, INV-17)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
from rag_core.clock import FakeClock
from rag_core.interfaces import TenantPolicy
from rag_core.providers.openai_compat import OpenAICompatibleLLM
from rag_core.types import ChatMessage, GenerationParams
from rag_gateway.routing import ModelRouter

NIF = "123456789"
MESSAGES = [ChatMessage(role="user", content=f"O meu NIF é {NIF}. Qual é o prazo?")]
PARAMS = GenerationParams()
CLOCK = FakeClock(datetime(2026, 5, 10, 12, 0, tzinfo=UTC))


class Upstream:
    """Servidor OpenAI-compatível falso que guarda os corpos recebidos."""

    def __init__(self, answer: str, pieces: list[str] | None = None) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.answer = answer
        self.pieces = pieces or [answer]

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        if body.get("stream"):
            events = [
                "data: " + json.dumps({"choices": [{"delta": {"content": piece}}]})
                for piece in self.pieces
            ]
            text = "\n\n".join([*events, "data: [DONE]", ""])
            return httpx.Response(200, text=text, headers={"content-type": "text/event-stream"})
        return httpx.Response(
            200,
            json={"model": "m", "choices": [{"message": {"content": self.answer}}]},
        )

    def provider(self, *, remote: bool) -> OpenAICompatibleLLM:
        return OpenAICompatibleLLM(
            "upstream", "https://llm.test/v1", "m", is_remote=remote,
            transport=httpx.MockTransport(self.handler),
        )  # fmt: skip


def _router(upstream: Upstream, *, remote: bool) -> ModelRouter:
    return ModelRouter({"primary": upstream.provider(remote=remote)}, CLOCK)


def _sent_text(upstream: Upstream) -> str:
    return " ".join(m["content"] for m in upstream.bodies[-1]["messages"])


def test_external_provider_receives_placeholders() -> None:
    upstream = Upstream("ok")
    router = _router(upstream, remote=True)
    router.generate(
        None, TenantPolicy(tenant_id="t", allowed_models=("primary",)), MESSAGES, PARAMS
    )
    sent = _sent_text(upstream)
    assert NIF not in sent and "[NIF_1]" in sent and "Qual é o prazo?" in sent
    list(
        router.stream(
            None, TenantPolicy(tenant_id="t", allowed_models=("primary",)), MESSAGES, PARAMS
        )
    )
    assert NIF not in _sent_text(upstream)


def test_response_rehydrated() -> None:
    upstream = Upstream("O NIF [NIF_1] está registado; [NIF_9] é desconhecido.")
    policy = TenantPolicy(tenant_id="t", allowed_models=("primary",))
    routed = _router(upstream, remote=True).generate(None, policy, MESSAGES, PARAMS)
    assert routed.result.text == f"O NIF {NIF} está registado; [NIF_9] é desconhecido."


def test_internal_provider_receives_original() -> None:
    upstream = Upstream(f"O NIF {NIF} aparece na resposta.")
    policy = TenantPolicy(tenant_id="t", allowed_models=("primary",))
    routed = _router(upstream, remote=False).generate(None, policy, MESSAGES, PARAMS)
    assert NIF in _sent_text(upstream) and "[NIF_1]" not in _sent_text(upstream)
    assert routed.result.text == f"O NIF {NIF} aparece na resposta."


def test_policy_can_disable_redaction() -> None:
    upstream = Upstream("ok")
    policy = TenantPolicy(tenant_id="t", allowed_models=("primary",), redact_pii_for_external=False)
    _router(upstream, remote=True).generate(None, policy, MESSAGES, PARAMS)
    assert NIF in _sent_text(upstream)


def test_stream_rehydration() -> None:
    # o marcador chega partido ao meio e nunca pode ser emitido incompleto
    upstream = Upstream("", pieces=["O seu NIF é [NI", "F_1] e mais", " texto ", "[NIF_1"])
    policy = TenantPolicy(tenant_id="t", allowed_models=("primary",))
    pieces = [
        text for _, text in _router(upstream, remote=True).stream(None, policy, MESSAGES, PARAMS)
    ]
    assert "".join(pieces) == f"O seu NIF é {NIF} e mais texto [NIF_1"
    assert not any(p.endswith("[NI") for p in pieces[:-1])
    assert NIF not in _sent_text(upstream)
