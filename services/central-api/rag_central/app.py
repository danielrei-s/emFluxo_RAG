"""Fábrica da aplicação da Central API (F8-T01).

Três superfícies: ``/v1`` (utilizadores), ``/internal/v1`` (serviços, F8-T06) e
``/backoffice/v1`` (F9). Sem CORS: o browser nunca fala diretamente com esta API.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from rag_core.config import Settings
from rag_core.web import install_standard_web

from rag_central import __version__
from rag_central.auth import CentralAuth
from rag_central.db import Database
from rag_central.signing import Signer

# 8 MB chega para metadados; os ficheiros entram por um endpoint próprio (F8-T02).
MAX_BODY_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class CentralDeps:
    """Dependências injetadas; ``/readyz`` verifica cada ``readiness``."""

    signer: Signer | None = None
    auth: CentralAuth | None = None
    db: Database | None = None
    readiness: Mapping[str, Callable[[], bool]] = field(default_factory=dict)


def create_app(settings: Settings, deps: CentralDeps | None = None) -> FastAPI:
    deps = deps or CentralDeps()
    app = FastAPI(
        title="RAG Central API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.deps = deps
    app.state.central_auth = deps.auth
    install_standard_web(app, MAX_BODY_BYTES)

    @app.get("/healthz", tags=["ops"], summary="Processo vivo")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"], summary="Dependências prontas")
    def readyz() -> JSONResponse:
        checks = {name: _safe(check) for name, check in deps.readiness.items()}
        ready = all(checks.values())
        return JSONResponse(
            {"status": "ready" if ready else "unavailable", "checks": checks},
            status_code=200 if ready else 503,
        )

    @app.get("/.well-known/jwks.json", tags=["ops"], summary="Chaves públicas de assinatura")
    def jwks() -> JSONResponse:
        keys = deps.signer.jwks() if deps.signer else {"keys": []}
        return JSONResponse(keys, headers={"Cache-Control": "public, max-age=300"})

    from rag_central.routers import backoffice, internal, users

    routers: tuple[tuple[str, APIRouter], ...] = (
        ("/v1", users.router),
        ("/internal/v1", internal.router),
        ("/backoffice/v1", backoffice.router),
    )
    for prefix, router in routers:
        app.include_router(router, prefix=prefix)
    return app


def _safe(check: Callable[[], bool]) -> bool:
    try:
        return bool(check())
    except Exception:  # uma verificação que falha conta como "não pronto", sem expor o erro
        return False


__all__ = ["CentralDeps", "create_app"]
