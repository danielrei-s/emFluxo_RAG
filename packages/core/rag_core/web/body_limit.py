"""Limite do corpo dos pedidos (256 KB por omissão): ``413`` em problem+json."""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from rag_core.errors import FileTooLarge
from rag_core.web.problem import problem_response

DEFAULT_MAX_BODY_BYTES = 256 * 1024


class BodyLimitMiddleware:
    """Recusa cedo pelo ``Content-Length``; sem ele (``chunked``) lê o corpo até ao limite.

    A leitura antecipada evita que o FastAPI converta o erro de leitura num ``400``: o pedido
    só chega à aplicação se o corpo couber no limite.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = DEFAULT_MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        await problem_response(413, FileTooLarge.code)(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            if declared.isdigit() and int(declared) > self.max_bytes:
                await self._reject(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return

        buffered: list[Message] = []
        received = 0
        more = True
        while more:
            message = await receive()
            buffered.append(message)
            if message["type"] != "http.request":  # desligou-se
                break
            received += len(message.get("body", b""))
            if received > self.max_bytes:
                await self._reject(scope, receive, send)
                return
            more = bool(message.get("more_body", False))

        replay = iter(buffered)

        async def replaying_receive() -> Message:
            return next(replay, {"type": "http.disconnect"})

        await self.app(scope, replaying_receive, send)
