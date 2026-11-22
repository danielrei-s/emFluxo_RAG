"""Portas do gateway (F6-T02): estado de dispositivos e resolução de utilizadores.

As implementações reais (Supabase e BD central) chegam com a F8-T06; aqui há fakes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from rag_core.types import Principal


class DeviceStatusProvider(Protocol):
    """Diz se um dispositivo ainda está autorizado (revogação imediata, INV-14)."""

    def is_active(self, tenant_id: str, user_id: str, device_id: str) -> bool: ...


class PrincipalResolver(Protocol):
    """Traduz as claims de um token Supabase (mais o dispositivo) num ``Principal``."""

    def resolve(self, claims: Mapping[str, Any], device_id: str) -> Principal | None: ...


class FakeDeviceStatusProvider:
    """Todos os dispositivos estão ativos, exceto os revogados."""

    def __init__(self) -> None:
        self._revoked: set[tuple[str, str, str]] = set()

    def revoke(self, tenant_id: str, user_id: str, device_id: str) -> None:
        self._revoked.add((tenant_id, user_id, device_id))

    def is_active(self, tenant_id: str, user_id: str, device_id: str) -> bool:
        return (tenant_id, user_id, device_id) not in self._revoked


class FakePrincipalResolver:
    """Mapa ``sub`` do token → ``Principal``."""

    def __init__(self, principals: Mapping[str, Principal] | None = None) -> None:
        self._principals = dict(principals or {})

    def resolve(self, claims: Mapping[str, Any], device_id: str) -> Principal | None:
        return self._principals.get(str(claims.get("sub")))


class NoDevices:
    """Sem Central API (F8-T06) nenhum dispositivo é aceite: só entram tokens de serviço."""

    def is_active(self, tenant_id: str, user_id: str, device_id: str) -> bool:
        return False


class NoPrincipals:
    """Idem para a resolução de utilizadores Supabase."""

    def resolve(self, claims: Mapping[str, Any], device_id: str) -> Principal | None:
        return None
