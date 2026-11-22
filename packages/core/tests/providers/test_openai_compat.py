"""Testes de F5-T02: clientes compatíveis com a API OpenAI (LLM e embeddings)."""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from pydantic import SecretStr
from rag_core.errors import UpstreamError, ValidationFailed
from rag_core.providers import OpenAICompatibleEmbedder, OpenAICompatibleLLM
from rag_core.types import ChatMessage, GenerationParams

BASE = "http://127.0.0.1:11434/v1"
MESSAGES = [
    ChatMessage(role="system", content="sistema"),
    ChatMessage(role="user", content="Pergunta: olá?"),
]
PARAMS = GenerationParams(max_tokens=50, temperature=0.2)


def _llm(**kwargs: Any) -> OpenAICompatibleLLM:
    kwargs.setdefault("sleep", lambda _: None)
    return OpenAICompatibleLLM("local", BASE, "modelo-x", **kwargs)


class _Chunks(httpx.SyncByteStream):
    """Corpo em pedaços arbitrários (a quebra pode cair a meio de uma linha SSE)."""

    def __init__(self, parts: list[bytes], error: Exception | None = None) -> None:
        self._parts = parts
        self._error = error

    def __iter__(self) -> Iterator[bytes]:
        yield from self._parts
        if self._error is not None:
            raise self._error


def _sse(parts: list[bytes], error: Exception | None = None) -> httpx.MockTransport:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, stream=_Chunks(parts, error))

    transport = httpx.MockTransport(handler)
    transport.calls = calls  # type: ignore[attr-defined]
    return transport


# ---------------------------------------------------------------------------- LLM


@respx.mock
def test_chat_completion_success() -> None:
    route = respx.post(f"{BASE}/chat/completions").respond(
        json={
            "model": "modelo-x-1.0",
            "choices": [
                {"message": {"role": "assistant", "content": "Olá!"}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        }
    )
    llm = _llm(api_key=SecretStr("chave-de-teste"), is_remote=True)
    result = llm.generate(MESSAGES, params=PARAMS)
    assert (result.text, result.model) == ("Olá!", "modelo-x-1.0")
    assert (result.tokens_in, result.tokens_out, result.finish_reason) == (12, 3, "stop")
    assert llm.is_remote is True and llm.name == "local"
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer chave-de-teste"
    assert json.loads(request.content) == {
        "model": "modelo-x",
        "messages": [
            {"role": "system", "content": "sistema"},
            {"role": "user", "content": "Pergunta: olá?"},
        ],
        "max_tokens": 50,
        "temperature": 0.2,
        "stream": False,
    }
    assert "chave-de-teste" not in repr(llm)


@respx.mock
def test_chat_without_key_and_with_sparse_response() -> None:
    route = respx.post(f"{BASE}/chat/completions").respond(
        json={"choices": [{"message": {"content": None}}]}
    )
    result = _llm().generate(MESSAGES, params=PARAMS)
    assert (result.text, result.model, result.tokens_in) == ("", "modelo-x", None)
    assert "authorization" not in route.calls.last.request.headers


def test_stream_parsing_with_split_chunks() -> None:
    body = (
        b": keep-alive\n\n"
        b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"Ol'
        b'\xc3\xa1"}}]}\n\n'  # um carácter UTF-8 partido entre pedaços
        b'data:{"choices":[{"delta":{"content":" mu"}}]}\n'  # sem espaço depois de "data:"
        b'data: {"choices":[{"delta":{"content":"ndo"'
        b"}}]}\n\n"
        b'data: {"choices":[{"delta":{"content":""}}]}\n\n'
        b"event: ping\n\n"
        b"data: [DONE]\n\n"
        b'data: {"choices":[{"delta":{"content":"nunca"}}]}\n\n'
    )
    pieces = [body[i : i + 7] for i in range(0, len(body), 7)]
    transport = _sse(pieces)
    text = list(_llm(transport=transport).stream(MESSAGES, params=PARAMS))
    assert "".join(text) == "Olá mundo"
    assert json.loads(transport.calls[0].content)["stream"] is True  # type: ignore[attr-defined]


def test_stream_event_split_over_multiple_data_lines() -> None:
    body = b'data: {"choices":[{"delta":\ndata: {"content":"x"}}]}\n\ndata: [DONE]\n'
    assert list(_llm(transport=_sse([body])).stream(MESSAGES, params=PARAMS)) == ["x"]
    body2 = b'data: {"choices":[{"delta":{"content"\ndata: :"junto"}}]}\n\ndata: [DONE]\n'
    assert list(_llm(transport=_sse([body2])).stream(MESSAGES, params=PARAMS)) == ["junto"]


def test_stream_errors() -> None:
    with pytest.raises(UpstreamError) as exc:
        list(_llm(transport=_sse([b'data: {"choices": []}\n\n'])).stream(MESSAGES, params=PARAMS))
    assert exc.value.detail_id == "invalid_stream"
    huge = b"data: " + b"x" * 1_100_000 + b"\n"
    with pytest.raises(UpstreamError):
        list(_llm(transport=_sse([huge])).stream(MESSAGES, params=PARAMS))


def test_no_retry_after_first_byte_of_a_stream() -> None:
    first = b'data: {"choices":[{"delta":{"content":"parcial"}}]}\n\n'
    transport = _sse([first], error=httpx.ReadError("ligação perdida"))
    stream = _llm(transport=transport).stream(MESSAGES, params=PARAMS)
    assert next(stream) == "parcial"
    with pytest.raises(UpstreamError) as exc:
        next(stream)
    assert exc.value.detail_id == "stream_interrupted"
    assert len(transport.calls) == 1  # type: ignore[attr-defined]


@respx.mock
def test_retry_on_429_then_success() -> None:
    sleeps: list[float] = []
    route = respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[
            httpx.Response(429, text="CANARIO-limite"),
            httpx.Response(503),
            httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}),
        ]
    )
    result = _llm(sleep=sleeps.append, max_retries=2).generate(MESSAGES, params=PARAMS)
    assert result.text == "ok"
    assert route.call_count == 3
    assert sleeps == [0.5, 1.0]  # backoff exponencial


@respx.mock
def test_retry_policy_limits() -> None:
    route = respx.post(f"{BASE}/chat/completions").respond(429)
    with pytest.raises(UpstreamError) as exc:
        _llm(max_retries=2).generate(MESSAGES, params=PARAMS)
    assert exc.value.detail_id == "http_429"
    assert route.call_count == 3
    before = route.call_count
    bad = respx.post(f"{BASE}/chat/completions").respond(400)
    with pytest.raises(UpstreamError) as exc2:
        _llm().generate(MESSAGES, params=PARAMS)
    assert exc2.value.detail_id == "http_400"
    assert bad.call_count - before == 1  # 4xx (exceto 429) não se repete


@respx.mock
def test_transport_failures_are_retried_then_reported() -> None:
    route = respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[
            httpx.ConnectError("sem rede"),
            httpx.Response(200, json={"choices": [{"message": {"content": "a"}}]}),
        ]
    )
    assert _llm().generate(MESSAGES, params=PARAMS).text == "a"
    assert route.call_count == 2
    respx.post(f"{BASE}/chat/completions").mock(side_effect=httpx.ReadTimeout("lento"))
    with pytest.raises(UpstreamError) as timeout:
        _llm(max_retries=1).generate(MESSAGES, params=PARAMS)
    assert timeout.value.detail_id == "timeout"
    respx.post(f"{BASE}/chat/completions").mock(side_effect=httpx.ConnectError("recusada"))
    with pytest.raises(UpstreamError) as connection:
        _llm(max_retries=0).generate(MESSAGES, params=PARAMS)
    assert connection.value.detail_id == "connection"


@respx.mock
def test_inv03_upstream_error_has_no_body_text() -> None:
    canary = "CANARIO-corpo-do-erro-SEGREDO"
    respx.post(f"{BASE}/chat/completions").respond(500, json={"error": {"message": canary}})
    with pytest.raises(UpstreamError) as exc:
        _llm(max_retries=0).generate(MESSAGES, params=PARAMS)
    assert canary not in str(exc.value)
    assert canary not in repr(exc.value)
    assert str(exc.value) == "upstream_error:http_500"
    respx.post(f"{BASE}/chat/completions").respond(200, text=f"não é json {canary}")
    with pytest.raises(UpstreamError) as invalid:
        _llm().generate(MESSAGES, params=PARAMS)
    assert canary not in str(invalid.value) and invalid.value.detail_id == "invalid_json"
    respx.post(f"{BASE}/chat/completions").respond(200, json=[canary])
    with pytest.raises(UpstreamError) as not_object:
        _llm().generate(MESSAGES, params=PARAMS)
    assert not_object.value.detail_id == "invalid_json"
    respx.post(f"{BASE}/chat/completions").respond(200, json={"choices": []})
    with pytest.raises(UpstreamError) as shape:
        _llm().generate(MESSAGES, params=PARAMS)
    assert shape.value.detail_id == "invalid_response"


# ------------------------------------------------------------------------ embeddings


def _embedder(**kwargs: Any) -> OpenAICompatibleEmbedder:
    kwargs.setdefault("sleep", lambda _: None)
    return OpenAICompatibleEmbedder("emb", BASE, "modelo-e", 3, **kwargs)


def _embedding_response(vectors: list[list[float]], *, shuffle: bool = False) -> httpx.Response:
    items = [{"index": i, "embedding": v} for i, v in enumerate(vectors)]
    return httpx.Response(200, json={"data": list(reversed(items)) if shuffle else items})


@respx.mock
def test_embedder_normalizes_orders_and_batches() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        return _embedding_response([[float(len(t)), 0.0, 0.0] for t in texts], shuffle=True)

    route = respx.post(f"{BASE}/embeddings").mock(side_effect=handler)
    embedder = _embedder(batch_size=2)
    vectors = embedder.embed_documents(["a", "bb", "ccc", "dddd", "e"])
    assert route.call_count == 3  # 2 + 2 + 1
    assert vectors == [[1.0, 0.0, 0.0]] * 5  # normalizados e pela ordem pedida
    assert embedder.embed_documents([]) == []
    assert all(math.isclose(math.sqrt(sum(x * x for x in v)), 1.0) for v in vectors)


@respx.mock
def test_embedder_zero_vector_is_kept() -> None:
    respx.post(f"{BASE}/embeddings").mock(return_value=_embedding_response([[0.0, 0.0, 0.0]]))
    assert _embedder().embed_query("x") == [0.0, 0.0, 0.0]


@respx.mock
def test_embedder_dim_mismatch_raises() -> None:
    respx.post(f"{BASE}/embeddings").mock(return_value=_embedding_response([[1.0, 2.0]]))
    with pytest.raises(ValidationFailed) as exc:
        _embedder().embed_query("texto")
    assert exc.value.subcode == "embedding_dimension_mismatch"


@respx.mock
def test_embedder_invalid_responses() -> None:
    respx.post(f"{BASE}/embeddings").respond(200, json={"data": [{"index": 0}]})
    with pytest.raises(UpstreamError):
        _embedder().embed_query("x")
    respx.post(f"{BASE}/embeddings").mock(return_value=_embedding_response([[1.0, 0.0, 0.0]] * 2))
    with pytest.raises(UpstreamError) as count:
        _embedder().embed_query("x")  # devolveu 2 vetores para 1 texto
    assert count.value.detail_id == "invalid_response"
    with pytest.raises(ValueError):
        OpenAICompatibleEmbedder("e", BASE, "m", 0)
    with pytest.raises(ValueError):
        OpenAICompatibleEmbedder("e", BASE, "m", 3, batch_size=0)


@respx.mock
def test_e5_prefixes_applied() -> None:
    route = respx.post(f"{BASE}/embeddings").mock(
        side_effect=lambda request: _embedding_response(
            [[1.0, 0.0, 0.0] for _ in json.loads(request.content)["input"]]
        )
    )
    embedder = _embedder(query_prefix="query: ", document_prefix="passage: ")
    embedder.embed_query("férias")
    embedder.embed_documents(["texto um", "texto dois"])
    sent = [json.loads(call.request.content)["input"] for call in route.calls]
    assert sent == [["query: férias"], ["passage: texto um", "passage: texto dois"]]
    plain = _embedder()  # o bge-m3 não leva prefixos
    plain.embed_query("férias")
    assert json.loads(route.calls.last.request.content)["input"] == ["férias"]
    assert plain.model_id == "emb" and plain.dim == 3


def test_clients_can_be_closed() -> None:
    _llm().close()
    _embedder().close()
