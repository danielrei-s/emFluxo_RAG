"""Testes do ``StaticPolicyProvider`` (políticas por tenant a partir de YAML)."""

from __future__ import annotations

from pathlib import Path

import pytest
from rag_core.errors import NotFound
from rag_core.interfaces import TenantPolicy
from rag_core.policy_provider import StaticPolicyProvider

YAML = """
default:
  rate_per_minute_user: 5
tenants:
  aurora:
    products: [web]
    monthly_token_quota: 1000
    allowed_models: [rag-default, rag-fallback]
  boreal:
    status: suspended
"""


def test_loads_tenants_and_applies_the_default(tmp_path: Path) -> None:
    path = tmp_path / "policies.yaml"
    path.write_text(YAML, encoding="utf-8")
    provider = StaticPolicyProvider.from_yaml(path)
    aurora = provider.get("aurora")
    assert aurora.tenant_id == "aurora" and aurora.monthly_token_quota == 1000
    assert aurora.allowed_models == ("rag-default", "rag-fallback")
    assert provider.get("boreal").status == "suspended"
    novo = provider.get("novo")  # tenant sem entrada: usa a política por omissão
    assert (novo.tenant_id, novo.rate_per_minute_user) == ("novo", 5)


def test_unknown_tenant_without_default_is_not_found(tmp_path: Path) -> None:
    provider = StaticPolicyProvider({"a": TenantPolicy(tenant_id="a")})
    assert provider.get("a").tenant_id == "a"
    with pytest.raises(NotFound):
        provider.get("b")
    empty = tmp_path / "vazio.yaml"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(NotFound):
        StaticPolicyProvider.from_yaml(empty).get("qualquer")
