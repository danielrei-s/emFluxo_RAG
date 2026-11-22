"""Cliente do Inference Gateway para a Central API (F8-T04): um token de serviço por pedido."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from typing import Any

import httpx
from rag_core.errors import (
    AccessDenied,
    BadRequest,
    PromptTooLarge,
    QuotaExceeded,
    RateLimited,
    UnsupportedFeature,
    UpstreamError,
)
from rag_core.types import ChatMessage, GenerationParams, LLMResult, Principal

from rag_central.signing import Signer

_SAFE = re.compile(r"[a-z0-9_]{1,64}")
DEFAULT_TIMEOUT_S = 120.0


class RetryableRateLimited(RateLimited):
    """``RateLimited`` com o ``Retry-After`` do gateway (o handler problem+json reencaminha-o)."""

    def __init__(self, retry_after_s: int, detail_id: str | None = None) -> None:
        super().__init__(detail_id)
        self.retry_after_s = retry_after_s


def _problem(response: httpx.Response) -> tuple[str, str | None]:
    """``(code, subcode)`` de um problem+json do gateway; nunca texto livre."""
    try:
        body = response.json()
        code, sub = str(body.get("code", "")), body.get("subcode")
    except (ValueError, AttributeError):
        return "", None
    return (
        code if _SAFE.fullmatch(code) else "",
        sub if isinstance(sub, str) and _SAFE.fullmatch(sub) else None,
    )


def raise_for_gateway_error(response: httpx.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    code, sub = _problem(response)
    if status == 429:
        if code == "quota_exceeded":
            raise QuotaExceeded(sub)
        header = response.headers.get("retry-after", "")
        raise RetryableRateLimited(int(header) if header.isdigit() else 60, sub)
    if status == 400:
        raise (UnsupportedFeature(sub) if code == "unsupported_feature" else BadRequest(sub))
    if status == 413:
        raise PromptTooLarge(sub)
    if status == 403:
        raise AccessDenied(sub)
    raise UpstreamError(sub or f"http_{status}")  # 401 (token recusado), 5xx, etc.


class GatewayLLMClient:
    """``LLMProvider`` remoto: cada chamada leva um token de serviço novo (60 s)."""

    name = "gateway"
    is_remote = True

    def __init__(
        self,
        base_url: str,
        signer: Signer,
        principal: Principal,
        *,
        model: str | None = None,
        purpose: str = "chat",
        timeout_s: float = DEFAULT_TIMEOUT_S,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._signer = signer
        self._principal = principal
        self._model = model
        self._purpose = purpose
        self._client = httpx.Client(timeout=timeout_s, transport=transport)

    def __repr__(self) -> str:
        return f"GatewayLLMClient(base_url={self._base!r}, model={self._model!r})"

    def _request(
        self, messages: Sequence[ChatMessage], params: GenerationParams, *, stream: bool
    ) -> httpx.Request:
        token = self._signer.mint_service_token(
            self._principal.tenant_id, self._principal.user_id, self._purpose
        )
        body: dict[str, Any] = {
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": params.max_tokens,
            "temperature": params.temperature,
            "stream": stream,
        }
        if self._model:
            body["model"] = self._model
        return self._client.build_request(
            "POST",
            f"{self._base}/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            content=json.dumps(body),
        )

    def _send(self, request: httpx.Request, *, stream: bool) -> httpx.Response:
        try:
            response = self._client.send(request, stream=stream)
        except httpx.TimeoutException as exc:
            raise UpstreamError("timeout") from exc
        except httpx.TransportError as exc:
            raise UpstreamError("connection") from exc
        if response.status_code >= 400:
            try:
                response.read()
                raise_for_gateway_error(response)
            finally:
                response.close()
        return response

    def generate(self, messages: Sequence[ChatMessage], *, params: GenerationParams) -> LLMResult:
        response = self._send(self._request(messages, params, stream=False), stream=False)
        try:
            data = response.json()
            choice = data["choices"][0]
            usage = data.get("usage") or {}
            return LLMResult(
                text=str(choice["message"]["content"] or ""),
                model=str(response.headers.get("x-model-alias") or data.get("model") or "gateway"),
                tokens_in=usage.get("prompt_tokens"),
                tokens_out=usage.get("completion_tokens"),
                finish_reason=choice.get("finish_reason"),
            )
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise UpstreamError("invalid_response") from exc

    def stream(self, messages: Sequence[ChatMessage], *, params: GenerationParams) -> Iterator[str]:
        response = self._send(self._request(messages, params, stream=True), stream=True)
        event = ""
        try:
            for raw in response.iter_lines():
                line = raw.strip()
                if line.startswith("event:"):
                    event = line[len("event:") :].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if event == "error":  # o gateway avisa que o fluxo caiu a meio
                    raise UpstreamError("stream_interrupted")
                if data == "[DONE]":
                    return
                try:
                    delta = json.loads(data)["choices"][0].get("delta") or {}
                except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
                    raise UpstreamError("invalid_stream") from exc
                if delta.get("content"):
                    yield str(delta["content"])
        except httpx.HTTPError as exc:
            raise UpstreamError("stream_interrupted") from exc
        finally:
            response.close()

    def close(self) -> None:
        self._client.close()
