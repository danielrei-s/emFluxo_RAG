"""Aplicação FastAPI do motor local (F11-T01); as rotas crescem com F11-T03 em diante."""

from __future__ import annotations

from fastapi import FastAPI
from rag_core.web.problem import install_problem_handlers

from rag_local import __version__
from rag_local.routers import documents, workspaces
from rag_local.security import LocalSecurityMiddleware
from rag_local.state import LocalState


def create_app(
    *, token: str, port: int, dev: bool = False, local: LocalState | None = None
) -> FastAPI:
    app = FastAPI(
        title="RAG Local Engine",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.local = local
    install_problem_handlers(app)
    app.include_router(workspaces.router, prefix="/v1")
    app.include_router(documents.router, prefix="/v1")
    app.add_middleware(LocalSecurityMiddleware, token=token, port=port, dev=dev)

    @app.get("/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app
