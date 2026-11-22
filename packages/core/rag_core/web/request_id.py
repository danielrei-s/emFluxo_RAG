"""``X-Request-Id``: aceita um UUID do cliente, senão gera um; devolve-o e liga-o aos logs."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADER = "x-request-id"
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def current_request_id() -> str | None:
    """O ``request_id`` do pedido em curso (ou ``None`` fora de um pedido)."""
    return _request_id.get()


def _valid_uuid(value: str) -> str | None:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


class RequestIdMiddleware:
    """Middleware ASGI puro (sem ``BaseHTTPMiddleware``, que perde o contexto em streaming)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = dict(scope["headers"]).get(HEADER.encode(), b"").decode("latin-1")
        request_id = _valid_uuid(supplied) or str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        token = _request_id.set(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
            _request_id.reset(token)
