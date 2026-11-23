"""Segurança do servidor local (F11-T01; INV-11): Host, Origin e token Bearer.

Ordem das verificações: ``Host`` (421, contra DNS rebinding) → ``Origin`` (403) → token (401).
O token nunca é escrito em logs nem em respostas.
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

TAURI_ORIGINS = frozenset(
    {"tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"}
)
DEV_ORIGINS = frozenset({"http://localhost:1420"})


def allowed_origins(dev: bool) -> frozenset[str]:
    return TAURI_ORIGINS | DEV_ORIGINS if dev else TAURI_ORIGINS


def allowed_hosts(port: int) -> frozenset[str]:
    return frozenset({f"127.0.0.1:{port}", f"localhost:{port}"})


async def _reject(send: Send, status: int, code: str, headers: list[tuple[bytes, bytes]]) -> None:
    body = json.dumps({"code": code}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), *headers],
        }
    )
    await send({"type": "http.response.body", "body": body})


class LocalSecurityMiddleware:
    def __init__(self, app: Any, *, token: str, port: int, dev: bool = False) -> None:
        self.app = app
        self._token = token.encode()
        self._hosts = allowed_hosts(port)
        self._origins = allowed_origins(dev)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        if headers.get("host", "") not in self._hosts:
            await _reject(send, 421, "misdirected_request", [])
            return
        origin = headers.get("origin")
        if origin is not None and origin not in self._origins:
            await _reject(send, 403, "origin_not_allowed", [])
            return
        cors: list[tuple[bytes, bytes]] = []
        if origin is not None:
            cors = [(b"access-control-allow-origin", origin.encode()), (b"vary", b"Origin")]
        if scope["method"] == "OPTIONS" and origin is not None:  # pré-voo: sem token
            cors += [
                (b"access-control-allow-methods", b"GET, POST, PUT, PATCH, DELETE, OPTIONS"),
                (b"access-control-allow-headers", b"authorization, content-type"),
                (b"access-control-max-age", b"600"),
            ]
            await send({"type": "http.response.start", "status": 204, "headers": cors})
            await send({"type": "http.response.body", "body": b""})
            return
        scheme, _, sent = headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(sent.encode(), self._token):
            await _reject(send, 401, "unauthenticated", [(b"www-authenticate", b"Bearer"), *cors])
            return

        async def send_with_cors(message: Message) -> None:
            if message["type"] == "http.response.start" and cors:
                message["headers"] = [*message.get("headers", []), *cors]
            await send(message)

        await self.app(scope, receive, send_with_cors)
