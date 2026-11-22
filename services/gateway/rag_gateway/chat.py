"""``POST /v1/chat/completions``: subconjunto compatível com OpenAI (F6-T05).

Só metadados saem daqui para logs e consumo (INV-03); ``tools`` e conteúdo não textual são
recusados (INV-09).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from rag_core.errors import (
    BadRequest,
    PromptTooLarge,
    RagError,
    UnsupportedFeature,
    UpstreamError,
)
from rag_core.interfaces import (
    Clock,
    TenantPolicy,
    TenantPolicyProvider,
    TokenCounter,
    UsageEvent,
    UsageRecorder,
)
from rag_core.logging import get_logger
from rag_core.tokens import ApproxTokenCounter
from rag_core.types import ChatMessage, GenerationParams, LLMResult
from rag_core.web.request_id import current_request_id

from rag_gateway.auth import AuthContext, require_auth
from rag_gateway.limits import GatewayLimiter
from rag_gateway.routing import ModelRouter

UNSUPPORTED_FIELDS = frozenset({"tools", "functions", "tool_choice", "function_call"})
SSE_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}


class ChatMessageIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: Literal["system", "user", "assistant"]
    content: str | list[Any]  # uma lista (partes com imagens, etc.) é recusada à mão


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")  # campos desconhecidos → 400 (não 422)

    messages: list[ChatMessageIn] = Field(min_length=1, max_length=64)
    model: str | None = Field(default=None, max_length=64)
    max_tokens: int | None = Field(default=None, ge=1)
    temperature: float = Field(default=0.1, ge=0.0, le=1.0)
    stream: bool = False


@dataclass
class ChatService:
    """Tudo o que o endpoint precisa; montado uma vez e guardado nas dependências do gateway."""

    policies: TenantPolicyProvider
    limiter: GatewayLimiter
    usage: UsageRecorder
    router: ModelRouter
    clock: Clock
    counter: TokenCounter = field(default_factory=ApproxTokenCounter)


def _validate(body: ChatCompletionRequest, policy: TenantPolicy) -> list[ChatMessage]:
    """Recusa o que o gateway não suporta e devolve as mensagens em texto."""
    extras = set(body.model_extra or {})
    if extras & UNSUPPORTED_FIELDS:
        raise UnsupportedFeature("tools")
    if extras:
        raise BadRequest("unknown_field")
    messages: list[ChatMessage] = []
    for message in body.messages:
        if message.model_extra:
            raise BadRequest("unknown_field")
        if not isinstance(message.content, str):
            raise UnsupportedFeature("non_text_content")
        messages.append(ChatMessage(role=message.role, content=message.content))
    if body.max_tokens is not None and body.max_tokens > policy.max_output_tokens:
        raise BadRequest("max_tokens_too_large")
    return messages


def _completion(
    rid: str, alias: str, result: LLMResult, tokens_in: int, tokens_out: int
) -> dict[str, Any]:
    return {
        "id": rid,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": alias,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.text},
                "finish_reason": result.finish_reason or "stop",
            }
        ],
        "usage": {
            "prompt_tokens": tokens_in,
            "completion_tokens": tokens_out,
            "total_tokens": tokens_in + tokens_out,
        },
    }


def _chunk(rid: str, alias: str, delta: dict[str, str], finish: str | None) -> str:
    payload = {
        "id": rid,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": alias,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


class _Metering:
    """Mede a latência e regista um único ``UsageEvent`` por pedido (sem conteúdo, INV-03)."""

    def __init__(self, service: ChatService, ctx: AuthContext, prompt_tokens: int) -> None:
        self._service = service
        self._ctx = ctx
        self.prompt_tokens = prompt_tokens
        self._start = time.perf_counter()
        self.ttft_ms: int | None = None
        self.alias = "-"

    def first_token(self) -> None:
        if self.ttft_ms is None:
            self.ttft_ms = int((time.perf_counter() - self._start) * 1000)

    def record(
        self,
        status: Literal["ok", "error", "rejected"],
        *,
        tokens_in: int | None = None,
        tokens_out: int = 0,
        error_code: str | None = None,
    ) -> None:
        principal = self._ctx.principal
        event = UsageEvent(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            device_id=self._ctx.device_id,
            model=self.alias,
            tokens_in=self.prompt_tokens if tokens_in is None else tokens_in,
            tokens_out=tokens_out,
            latency_ms=int((time.perf_counter() - self._start) * 1000),
            ttft_ms=self.ttft_ms,
            status=status,
            error_code=error_code,
            at=self._service.clock.now(),
        )
        self._service.usage.record(event)
        get_logger("gateway").info(
            "chat_completion",
            tenant_id=event.tenant_id,
            model=event.model,
            status=status,
            error_code=error_code,
            tokens_in=event.tokens_in,
            tokens_out=event.tokens_out,
            latency_ms=event.latency_ms,
            ttft_ms=event.ttft_ms,
        )


def _stream_events(
    rid: str,
    meter: _Metering,
    router_stream: Iterator[tuple[str, str]],
    first: tuple[str, str],
    counter: TokenCounter,
) -> Iterator[str]:
    alias, piece = first
    pieces = [piece]
    try:
        yield _chunk(rid, alias, {"role": "assistant"}, None)
        yield _chunk(rid, alias, {"content": piece}, None)
        for _, piece in router_stream:
            pieces.append(piece)
            yield _chunk(rid, alias, {"content": piece}, None)
    except UpstreamError as exc:
        meter.record("error", tokens_out=counter.count("".join(pieces)), error_code=exc.code)
        body = {"error": {"code": exc.code, "request_id": rid}}
        yield f"event: error\ndata: {json.dumps(body)}\n\n"
        return
    except GeneratorExit:  # o cliente desligou-se a meio
        meter.record("error", tokens_out=counter.count("".join(pieces)), error_code="client_gone")
        raise
    yield _chunk(rid, alias, {}, "stop")
    yield "data: [DONE]\n\n"
    meter.record("ok", tokens_out=counter.count("".join(pieces)))


def build_router(service_of: Callable[[Request], ChatService | None]) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["chat"])

    @router.post(
        "/chat/completions",
        summary="Geração de texto (subconjunto compatível com OpenAI)",
        response_model=None,
    )
    def chat_completions(
        request: Request,
        body: ChatCompletionRequest,
        ctx: AuthContext = Depends(require_auth),  # noqa: B008
    ) -> JSONResponse | StreamingResponse:
        service = service_of(request)
        if service is None:
            raise UpstreamError("chat_not_configured")
        principal = ctx.principal
        policy = service.policies.get(principal.tenant_id)
        rid = current_request_id() or "-"
        meter = _Metering(service, ctx, 0)
        try:
            messages = _validate(body, policy)
            prompt_tokens = sum(service.counter.count(m.content) for m in messages)
            meter.prompt_tokens = prompt_tokens
            if prompt_tokens > policy.max_prompt_tokens:
                raise PromptTooLarge()
            max_tokens = body.max_tokens or policy.max_output_tokens
            params = GenerationParams(max_tokens=max_tokens, temperature=body.temperature)
            service.limiter.check(principal, policy, prompt_tokens + max_tokens)
            meter.alias = service.router.order(body.model, policy)[0]
        except RagError as exc:
            meter.record("rejected", error_code=exc.code)
            raise
        try:
            if body.stream:
                return _start_stream(service, body, policy, messages, params, meter, rid)
            routed = service.router.generate(body.model, policy, messages, params)
        except RagError as exc:
            meter.record("error", error_code=exc.code)
            raise
        meter.alias = routed.alias
        meter.first_token()
        result = routed.result
        tokens_in = result.tokens_in if result.tokens_in is not None else prompt_tokens
        tokens_out = (
            result.tokens_out
            if result.tokens_out is not None
            else service.counter.count(result.text)
        )
        meter.record("ok", tokens_in=tokens_in, tokens_out=tokens_out)
        return JSONResponse(
            _completion(rid, routed.alias, result, tokens_in, tokens_out),
            headers={"X-Model-Alias": routed.alias},
        )

    return router


def _start_stream(
    service: ChatService,
    body: ChatCompletionRequest,
    policy: TenantPolicy,
    messages: list[ChatMessage],
    params: GenerationParams,
    meter: _Metering,
    rid: str,
) -> StreamingResponse:
    """Espera pelo 1.º pedaço (para o fallback e os cabeçalhos) e depois reemite em SSE."""
    pieces = service.router.stream(body.model, policy, messages, params)
    first = next(pieces, None)
    if first is None:
        first = (meter.alias, "")
    meter.alias = first[0]
    meter.first_token()
    events = _stream_events(rid, meter, pieces, first, service.counter)
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={**SSE_HEADERS, "X-Model-Alias": meter.alias},
    )
