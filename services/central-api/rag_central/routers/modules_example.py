"""Módulo de exemplo (só para testes dos pontos de extensão; F9-T02)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from rag_core.types import Principal

from rag_central.features import require_feature

router = APIRouter(prefix="/modules/example", tags=["modules"])


@router.get("/ping")
def ping(_: Principal = Depends(require_feature("example"))) -> dict[str, str]:  # noqa: B008
    return {"pong": "ok"}
