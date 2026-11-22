"""Erros HTTP em ``application/problem+json`` (C12) sem nunca incluir conteúdo (INV-03)."""

from __future__ import annotations

from typing import Any, cast

from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from rag_core import errors
from rag_core.logging import get_logger
from rag_core.web.request_id import current_request_id

PROBLEM_CONTENT_TYPE = "application/problem+json"

# RagError.code -> estado HTTP
STATUS_BY_CODE: dict[str, int] = {
    errors.ValidationFailed.code: 422,
    errors.UnsupportedType.code: 415,
    errors.FileTooLarge.code: 413,
    errors.EncryptedFile.code: 422,
    errors.CorruptedFile.code: 422,
    errors.ParseTimeout.code: 422,
    errors.ParseMemoryLimit.code: 422,
    errors.Unauthenticated.code: 401,
    errors.AccessDenied.code: 403,
    errors.ConsentError.code: 403,
    errors.NotFound.code: 404,
    errors.QuotaExceeded.code: 429,
    errors.RateLimited.code: 429,
    errors.UpstreamError.code: 502,
}
_TITLES = {
    400: "Pedido inválido",
    401: "Não autenticado",
    403: "Acesso negado",
    404: "Não encontrado",
    405: "Método não permitido",
    413: "Corpo demasiado grande",
    415: "Tipo não suportado",
    422: "Validação falhou",
    429: "Demasiados pedidos",
    502: "Falha no serviço a montante",
    503: "Serviço indisponível",
}


def problem_response(
    status: int,
    code: str,
    *,
    subcode: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """``{"type", "title", "status", "code", "subcode", "request_id"}``; o texto nunca é livre."""
    body: dict[str, Any] = {
        "type": f"urn:rag:error:{code}",
        "title": _TITLES.get(status, "Erro interno"),
        "status": status,
        "code": code,
        "request_id": current_request_id(),
    }
    if subcode:
        body["subcode"] = subcode
    return JSONResponse(
        body, status_code=status, media_type=PROBLEM_CONTENT_TYPE, headers=headers or {}
    )


def _rag_error(_: Request, exc: Exception) -> JSONResponse:
    error = cast(errors.RagError, exc)
    status = STATUS_BY_CODE.get(error.code, 500)
    subcode = error.subcode if isinstance(error, errors.ValidationFailed) else None
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return problem_response(status, error.code, subcode=subcode, headers=headers)


def _http_error(_: Request, exc: Exception) -> JSONResponse:
    error = cast(StarletteHTTPException, exc)
    code = {404: "not_found", 405: "method_not_allowed"}.get(error.status_code, "http_error")
    return problem_response(error.status_code, code, headers=dict(error.headers or {}))


def _request_validation(_: Request, exc: Exception) -> JSONResponse:
    # os detalhes do pydantic ecoam o valor recebido: nunca saem (INV-03)
    return problem_response(422, errors.ValidationFailed.code, subcode="invalid_request")


class UnhandledErrorMiddleware:
    """Apanha o que escapa aos handlers e responde com um problem+json genérico (INV-03).

    Fica *dentro* dos outros middlewares (ao contrário do handler ``Exception`` do Starlette,
    que corre fora deles), para a resposta levar ``X-Request-Id`` e os cabeçalhos de segurança.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            get_logger("web").error("unhandled_error", exc_type=type(exc).__name__)
            if started:  # a resposta já saiu em parte: não há como substituí-la
                raise
            await problem_response(500, "internal_error")(scope, receive, send)


def install_problem_handlers(app: Any) -> None:
    """Regista os handlers de erro numa aplicação FastAPI/Starlette."""
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(errors.RagError, _rag_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _request_validation)


def install_standard_web(app: Any, max_body_bytes: int | None = None) -> None:
    """Handlers de erro e middlewares comuns, pela ordem certa (do exterior para o interior):

    ``X-Request-Id`` → cabeçalhos de segurança → limite do corpo → erros não tratados.
    """
    from rag_core.web.body_limit import DEFAULT_MAX_BODY_BYTES, BodyLimitMiddleware
    from rag_core.web.request_id import RequestIdMiddleware
    from rag_core.web.security_headers import SecurityHeadersMiddleware

    install_problem_handlers(app)
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(BodyLimitMiddleware, max_bytes=max_body_bytes or DEFAULT_MAX_BODY_BYTES)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)
