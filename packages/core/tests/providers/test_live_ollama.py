"""Teste real contra um servidor compatível com OpenAI (marcador ``live``; manual, Máquina 1).

Só corre com ``RAG_LIVE_OLLAMA_URL`` definido (inclui ``/v1``). Modelos por omissão: os de
``models.example.yaml``; podem ser trocados com ``RAG_LIVE_CHAT_MODEL`` e ``RAG_LIVE_EMBED_MODEL``.
"""

from __future__ import annotations

import os

import pytest
from rag_core.providers import OpenAICompatibleEmbedder, OpenAICompatibleLLM
from rag_core.types import ChatMessage, GenerationParams

URL = os.environ.get("RAG_LIVE_OLLAMA_URL")
pytestmark = [
    pytest.mark.live,
    pytest.mark.enable_socket,
    pytest.mark.skipif(not URL, reason="RAG_LIVE_OLLAMA_URL não definido"),
]


def test_live_ollama_chat_and_embeddings() -> None:
    assert URL is not None
    chat_model = os.environ.get("RAG_LIVE_CHAT_MODEL", "qwen2.5:7b-instruct")
    embed_model = os.environ.get("RAG_LIVE_EMBED_MODEL", "bge-m3")
    llm = OpenAICompatibleLLM("live", URL, chat_model, timeout_s=300)
    messages = [ChatMessage(role="user", content="Responde apenas com a palavra: ok")]
    params = GenerationParams(max_tokens=20, temperature=0.0)
    assert llm.generate(messages, params=params).text.strip()
    assert "".join(llm.stream(messages, params=params)).strip()

    embedder = OpenAICompatibleEmbedder("live-embed", URL, embed_model, dim=1024)
    vectors = embedder.embed_documents(["dias de férias", "receita de bolo"])
    assert len(vectors) == 2 and all(len(v) == 1024 for v in vectors)
    query = embedder.embed_query("quantos dias de férias?")
    similarity = [sum(a * b for a, b in zip(query, v, strict=True)) for v in vectors]
    assert similarity[0] > similarity[1]
