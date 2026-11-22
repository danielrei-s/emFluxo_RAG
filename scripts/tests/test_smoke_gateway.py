"""Testes de F6-T07: o script de smoke do gateway."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import smoke_gateway  # noqa: E402

SSE = "data: {}\n\ndata: [DONE]\n\n"


def _client(*, ready: int = 200, anonymous: int = 401, chat: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/readyz":
            return httpx.Response(ready, json={})
        if "authorization" not in request.headers:
            return httpx.Response(anonymous, json={})
        if b'"stream"' in request.content:
            return httpx.Response(chat, text=SSE)
        return httpx.Response(
            chat, json={"choices": [{}]}, headers={"x-model-alias": "rag-default"}
        )

    return httpx.Client(base_url="https://gw.test", transport=httpx.MockTransport(handler))


def test_all_green() -> None:
    assert smoke_gateway.run_smoke(_client(), "tok") == []


def test_without_token_only_checks_the_public_parts() -> None:
    assert smoke_gateway.run_smoke(_client(), None) == []


def test_failures_are_reported() -> None:
    failures = smoke_gateway.run_smoke(_client(ready=503, anonymous=200, chat=502), "tok")
    assert len(failures) == 4 and any("readyz" in f for f in failures)
    assert any("401" in f for f in failures) and any("stream" in f for f in failures)


def test_main_reads_the_token_from_a_file_and_never_prints_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    token_file = tmp_path / "token.txt"
    token_file.write_text("SEGREDO-do-token\n", encoding="utf-8")
    real = httpx.Client
    good, not_ready = _client()._transport, _client(ready=503)._transport
    monkeypatch.setattr(
        smoke_gateway.httpx,
        "Client",
        lambda **kw: real(base_url=kw["base_url"], transport=good),
    )
    code = smoke_gateway.main(["--url", "https://gw.test", "--token-file", str(token_file)])
    out = capsys.readouterr()
    assert code == 0 and "smoke OK" in out.out
    assert "SEGREDO" not in out.out + out.err
    monkeypatch.setattr(
        smoke_gateway.httpx,
        "Client",
        lambda **kw: real(base_url=kw["base_url"], transport=not_ready),
    )
    assert smoke_gateway.main(["--url", "https://gw.test"]) == 1
