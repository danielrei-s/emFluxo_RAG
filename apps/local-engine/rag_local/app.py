"""Aplicação FastAPI do motor local (F11-T01); as rotas crescem com F11-T03 em diante."""

from __future__ import annotations

from fastapi import FastAPI

from rag_local import __version__
from rag_local.security import LocalSecurityMiddleware


def create_app(*, token: str, port: int, dev: bool = False) -> FastAPI:
    app = FastAPI(
        title="RAG Local Engine",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(LocalSecurityMiddleware, token=token, port=port, dev=dev)

    @app.get("/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app
