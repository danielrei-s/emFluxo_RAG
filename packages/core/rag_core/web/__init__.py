"""Peças HTTP partilhadas pelos serviços FastAPI (extra ``web``)."""

from rag_core.web.body_limit import DEFAULT_MAX_BODY_BYTES, BodyLimitMiddleware
from rag_core.web.problem import (
    UnhandledErrorMiddleware,
    install_problem_handlers,
    install_standard_web,
    problem_response,
)
from rag_core.web.request_id import RequestIdMiddleware, current_request_id
from rag_core.web.security_headers import SecurityHeadersMiddleware

__all__ = [
    "DEFAULT_MAX_BODY_BYTES",
    "BodyLimitMiddleware",
    "RequestIdMiddleware",
    "SecurityHeadersMiddleware",
    "UnhandledErrorMiddleware",
    "current_request_id",
    "install_problem_handlers",
    "install_standard_web",
    "problem_response",
]
