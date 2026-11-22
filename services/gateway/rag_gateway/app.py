"""Fábrica da aplicação do Inference Gateway (F6-T01)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from rag_core.config import Settings

from rag_gateway import __version__
from rag_gateway.middleware import install_middleware


@dataclass(frozen=True)
class GatewayDeps:
    """Dependências injetadas (``/readyz`` verifica cada uma; os testes passam as suas)."""

    readiness: Mapping[str, Callable[[], bool]] = field(default_factory=dict)


def create_app(settings: Settings, deps: GatewayDeps | None = None) -> FastAPI:
    """Cria a aplicação. Endpoints síncronos (``def``); sem UI de documentação pública."""
    deps = deps or GatewayDeps()
    app = FastAPI(
        title="RAG Inference Gateway",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.deps = deps
    install_middleware(app)

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

    return app


def _safe(check: Callable[[], bool]) -> bool:
    try:
        return bool(check())
    except Exception:  # uma verificação que falha conta como "não pronto", sem expor o erro
        return False
