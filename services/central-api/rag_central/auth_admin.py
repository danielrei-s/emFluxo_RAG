"""Administração de identidades (convites): ``AuthAdmin`` com Supabase e um falso (F8-T10)."""

from __future__ import annotations

import uuid
from typing import Protocol

import httpx
from pydantic import SecretStr
from rag_core.errors import UpstreamError


class AuthAdmin(Protocol):
    def invite(self, email: str, redirect_to: str | None) -> str:
        """Envia o convite e devolve o id (uuid) do utilizador no serviço de identidade."""
        ...


class FakeAuthAdmin:
    """Ids determinísticos por email; guarda os convites para os testes."""

    def __init__(self) -> None:
        self.invites: list[tuple[str, str | None]] = []

    def invite(self, email: str, redirect_to: str | None) -> str:
        self.invites.append((email, redirect_to))
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"invite:{email.lower()}"))


class SupabaseAuthAdmin:
    """``POST /auth/v1/invite`` com a chave de serviço (nunca sai do servidor, INV-13)."""

    def __init__(
        self,
        base_url: str,
        service_role_key: SecretStr,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._key = service_role_key
        self._http = httpx.Client(timeout=10.0, transport=transport)

    def invite(self, email: str, redirect_to: str | None) -> str:
        key = self._key.get_secret_value()
        try:
            response = self._http.post(
                f"{self._base}/auth/v1/invite",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
                params={"redirect_to": redirect_to} if redirect_to else None,
                json={"email": email},
            )
        except httpx.HTTPError as exc:
            raise UpstreamError("auth_admin_unreachable") from exc
        if response.status_code >= 400:
            raise UpstreamError(f"auth_admin_http_{response.status_code}")
        try:
            return str(uuid.UUID(str(response.json()["id"])))
        except (ValueError, KeyError, TypeError) as exc:
            raise UpstreamError("auth_admin_invalid_response") from exc
