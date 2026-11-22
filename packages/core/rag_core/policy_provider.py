"""Políticas por tenant (F6-T03): ``TenantPolicyProvider`` estático a partir de YAML."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from rag_core.errors import NotFound
from rag_core.interfaces import TenantPolicy


class StaticPolicyProvider:
    """Políticas fixas em memória: um tenant desconhecido usa ``default`` ou dá ``NotFound``."""

    def __init__(
        self, policies: Mapping[str, TenantPolicy], default: TenantPolicy | None = None
    ) -> None:
        self._policies = dict(policies)
        self._default = default

    @classmethod
    def from_yaml(cls, path: Path) -> StaticPolicyProvider:
        """``tenants: {id: {campos de TenantPolicy}}`` e, opcional, ``default: {...}``."""
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        policies = {
            tenant_id: TenantPolicy.model_validate({**fields, "tenant_id": tenant_id})
            for tenant_id, fields in (data.get("tenants") or {}).items()
        }
        raw_default = data.get("default")
        default = (
            TenantPolicy.model_validate({**raw_default, "tenant_id": "default"})
            if raw_default is not None
            else None
        )
        return cls(policies, default)

    def get(self, tenant_id: str) -> TenantPolicy:
        policy = self._policies.get(tenant_id)
        if policy is not None:
            return policy
        if self._default is not None:
            return self._default.model_copy(update={"tenant_id": tenant_id})
        raise NotFound("tenant_policy")
