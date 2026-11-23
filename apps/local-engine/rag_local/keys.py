"""Chave do índice local no keychain do sistema (F11-T02; INV-13).

A chave (32 bytes aleatórios) nunca sai do keyring nem é escrita em ficheiros ou logs.
"""

from __future__ import annotations

import secrets

import keyring
from keyring.errors import KeyringError, PasswordDeleteError
from rag_core.errors import UpstreamError

SERVICE = "rag-local"
KEY_BYTES = 32


class KeyUnavailableError(UpstreamError):
    """O keychain do sistema não está disponível."""


class KeyManager:
    def __init__(self, profile: str) -> None:
        self._account = f"db-key:{profile}"

    def get(self) -> bytes | None:
        """A chave existente ou ``None`` (nunca cria)."""
        try:
            value = keyring.get_password(SERVICE, self._account)
        except KeyringError as exc:
            raise KeyUnavailableError("keychain_unavailable") from exc
        return bytes.fromhex(value) if value else None

    def create(self) -> bytes:
        """Cria e guarda uma chave nova; recusa se já existir uma."""
        if self.get() is not None:
            raise KeyUnavailableError("key_exists")
        key = secrets.token_bytes(KEY_BYTES)
        try:
            keyring.set_password(SERVICE, self._account, key.hex())
        except KeyringError as exc:
            raise KeyUnavailableError("keychain_unavailable") from exc
        return key

    def delete(self) -> None:
        try:
            keyring.delete_password(SERVICE, self._account)
        except PasswordDeleteError:
            pass
        except KeyringError as exc:
            raise KeyUnavailableError("keychain_unavailable") from exc
