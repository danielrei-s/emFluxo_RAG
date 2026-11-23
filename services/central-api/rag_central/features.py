"""Funcionalidades por tenant (F9-T02; INV-19): ``require_feature`` dá 404 se estiver desligada."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, Request
from rag_core.errors import NotFound, UpstreamError
from rag_core.interfaces import Clock
from rag_core.modules import ModuleRegistry
from rag_core.types import Principal

from rag_central.auth import get_principal
from rag_central.db import Database

CACHE_TTL_S = 60


class FeatureService:
    def __init__(
        self, db: Database, registry: ModuleRegistry, clock: Clock, ttl_s: int = CACHE_TTL_S
    ) -> None:
        self._db = db
        self._registry = registry
        self._clock = clock
        self._ttl = ttl_s
        self._cache: dict[tuple[str, str], tuple[float, bool, dict[str, Any]]] = {}

    def state(self, tenant_id: str, user_id: str, name: str) -> tuple[bool, dict[str, Any]]:
        """``(ativa, config)``; sem linha na BD vale o ``default_enabled`` do manifesto."""
        now = self._clock.now().timestamp()
        hit = self._cache.get((tenant_id, name))
        if hit is not None and hit[0] > now:
            return hit[1], hit[2]
        manifest = self._registry.get(name)
        with self._db.tenant_tx(tenant_id, user_id) as cur:
            cur.execute(
                "select enabled, config from app.tenant_features "
                "where tenant_id = %s and feature = %s",
                (tenant_id, name),
            )
            row = cur.fetchone()
        enabled = bool(row["enabled"]) if row else manifest.default_enabled
        config: dict[str, Any] = dict(row["config"]) if row else {}
        self._cache[(tenant_id, name)] = (now + self._ttl, enabled, config)
        return enabled, config


def require_feature(name: str) -> Callable[..., Principal]:
    """Dependência FastAPI: 404 (e não 403) quando a funcionalidade está desligada."""

    def dependency(
        request: Request,
        principal: Principal = Depends(get_principal),  # noqa: B008
    ) -> Principal:
        service: FeatureService | None = request.app.state.deps.features
        if service is None:
            raise UpstreamError("features_not_configured")
        enabled, _ = service.state(principal.tenant_id, principal.user_id, name)
        if not enabled:
            raise NotFound()
        return principal

    return dependency
