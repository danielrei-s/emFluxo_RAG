"""Clientes compatíveis com a API OpenAI (F5-T02): LLM e embeddings.

Um só código serve Ollama, llama.cpp, vLLM, TGI e HF Endpoints; só muda a configuração. O
``base_url`` inclui ``/v1``. Os erros nunca incluem o corpo da resposta (INV-03).
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any

import httpx
from pydantic import SecretStr

from rag_core.errors import UpstreamError, ValidationFailed
from rag_core.types import ChatMessage, GenerationParams, LLMResult

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
BACKOFF_BASE_S = 0.5
_MAX_BUFFERED_EVENT = 1_000_000  # bytes de um evento SSE partido em várias linhas


class _Http:
    """Cliente httpx com cabeçalhos, repetições com backoff e erros sem corpo."""

    def __init__(
        self,
        base_url: str,
        api_key: SecretStr | None,
        timeout_s: float,
        max_retries: int,
        sleep: Callable[[float], None],
        transport: httpx.BaseTransport | None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Content-Type": "application/json"}
        if api_key is not None:
            self._headers["Authorization"] = f"Bearer {api_key.get_secret_value()}"
        self._client = httpx.Client(timeout=timeout_s, transport=transport)
        self._max_retries = max_retries
        self._sleep = sleep

    def _backoff(self, attempt: int) -> None:
        self._sleep(BACKOFF_BASE_S * (2**attempt))

    def _send(self, path: str, payload: dict[str, Any], *, stream: bool) -> httpx.Response:
        """Envia o pedido e repete em 429/5xx e falhas de rede; nunca expõe o corpo."""
        request = self._client.build_request(
            "POST", f"{self._base}{path}", headers=self._headers, content=json.dumps(payload)
        )
        for attempt in range(self._max_retries + 1):
            last = attempt == self._max_retries
            try:
                response = self._client.send(request, stream=stream)
            except httpx.TimeoutException as exc:
                if last:
                    raise UpstreamError("timeout") from exc
            except httpx.TransportError as exc:
                if last:
                    raise UpstreamError("connection") from exc
            else:
                if response.status_code < 400:
                    return response
                retry = response.status_code in RETRYABLE_STATUS and not last
                status = response.status_code
                response.close()
                if not retry:
                    raise UpstreamError(f"http_{status}")
            self._backoff(attempt)
        raise UpstreamError("exhausted")  # pragma: no cover - o ciclo termina sempre antes

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._send(path, payload, stream=False)
        try:
            data = response.json()
        except ValueError as exc:
            raise UpstreamError("invalid_json") from exc
        if not isinstance(data, dict):
            raise UpstreamError("invalid_json")
        return data

    def stream_lines(self, path: str, payload: dict[str, Any]) -> Iterator[str]:
        response = self._send(path, payload, stream=True)  # repetições só até aqui
        try:
            yield from response.iter_lines()
        except httpx.HTTPError as exc:  # a meio do fluxo já não se repete
            raise UpstreamError("stream_interrupted") from exc
        finally:
            response.close()

    def close(self) -> None:
        self._client.close()


def _messages(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
    return [{"role": m.role, "content": m.content} for m in messages]


def _payload(
    model: str, messages: Sequence[ChatMessage], params: GenerationParams, *, stream: bool
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": _messages(messages),
        "max_tokens": params.max_tokens,
        "temperature": params.temperature,
        "stream": stream,
    }


class OpenAICompatibleLLM:
    """``POST {base_url}/chat/completions`` com streaming SSE."""

    def __init__(
        self,
        name: str,
        base_url: str,
        model: str,
        api_key: SecretStr | None = None,
        timeout_s: float = 120.0,
        max_retries: int = 2,
        is_remote: bool = False,
        *,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.name = name
        self.is_remote = is_remote
        self._model = model
        self._http = _Http(base_url, api_key, timeout_s, max_retries, sleep, transport)

    def __repr__(self) -> str:  # sem a chave (INV-13)
        return f"OpenAICompatibleLLM(name={self.name!r}, model={self._model!r})"

    def generate(self, messages: Sequence[ChatMessage], *, params: GenerationParams) -> LLMResult:
        data = self._http.post_json(
            "/chat/completions", _payload(self._model, messages, params, stream=False)
        )
        try:
            choice = data["choices"][0]
            text = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise UpstreamError("invalid_response") from exc
        usage = data.get("usage") or {}
        return LLMResult(
            text=str(text or ""),
            model=str(data.get("model") or self._model),
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
            finish_reason=choice.get("finish_reason"),
        )

    def stream(self, messages: Sequence[ChatMessage], *, params: GenerationParams) -> Iterator[str]:
        buffer = ""
        payload = _payload(self._model, messages, params, stream=True)
        for line in self._http.stream_lines("/chat/completions", payload):
            line = line.strip()
            if not line or line.startswith(":") or not line.startswith("data:"):
                continue
            body = line[len("data:") :].strip()
            if body == "[DONE]":
                return
            buffer += body  # um evento pode vir partido em várias linhas ``data:``
            try:
                event = json.loads(buffer)
            except json.JSONDecodeError as exc:
                if len(buffer) > _MAX_BUFFERED_EVENT:
                    raise UpstreamError("invalid_stream") from exc
                continue
            buffer = ""
            try:
                delta = event["choices"][0].get("delta") or {}
            except (KeyError, IndexError, TypeError, AttributeError) as exc:
                raise UpstreamError("invalid_stream") from exc
            if delta.get("content"):
                yield str(delta["content"])

    def close(self) -> None:
        self._http.close()


class OpenAICompatibleEmbedder:
    """``POST {base_url}/embeddings``; valida a dimensão e normaliza (L2)."""

    def __init__(
        self,
        model_id: str,
        base_url: str,
        model: str,
        dim: int,
        batch_size: int = 32,
        query_prefix: str = "",
        document_prefix: str = "",
        api_key: SecretStr | None = None,
        timeout_s: float = 60.0,
        max_retries: int = 2,
        *,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if dim < 1 or batch_size < 1:
            raise ValueError("dim e batch_size têm de ser positivos")
        self.model_id = model_id
        self.dim = dim
        self._model = model
        self._batch = batch_size
        self._query_prefix = query_prefix
        self._document_prefix = document_prefix
        self._http = _Http(base_url, api_key, timeout_s, max_retries, sleep, transport)

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        data = self._http.post_json("/embeddings", {"model": self._model, "input": list(texts)})
        try:
            items = sorted(data["data"], key=lambda item: item["index"])
            vectors = [[float(x) for x in item["embedding"]] for item in items]
        except (KeyError, TypeError, ValueError) as exc:
            raise UpstreamError("invalid_response") from exc
        if len(vectors) != len(texts):
            raise UpstreamError("invalid_response")
        result = []
        for vector in vectors:
            if len(vector) != self.dim:
                raise ValidationFailed(subcode="embedding_dimension_mismatch")
            norm = math.sqrt(sum(x * x for x in vector))
            result.append([x / norm for x in vector] if norm > 0 else vector)
        return result

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch):
            batch = [self._document_prefix + t for t in texts[start : start + self._batch]]
            vectors.extend(self._embed(batch))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self._query_prefix + text])[0]

    def close(self) -> None:
        self._http.close()
