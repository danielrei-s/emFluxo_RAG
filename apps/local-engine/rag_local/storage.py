"""Índice local encriptado (SQLCipher) com a chave no keychain (F11-T02).

Regra de ouro: com uma base de dados existente e a chave em falta o estado é ``key_lost``; nunca
se cria uma chave nova por cima de uma base existente (apagaria o acesso aos dados sem avisar).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

import sqlcipher3
from rag_core.errors import ValidationFailed
from rag_core.stores import SqliteVectorStore

from rag_local.keys import KeyManager


class StorageState(StrEnum):
    NEW = "new"  # sem base nem chave: pode criar-se
    READY = "ready"  # base e chave presentes
    KEY_LOST = "key_lost"  # base sem chave: oferecer "reiniciar o índice local"


def open_encrypted(path: Path, key: bytes) -> Any:
    """Abre (ou cria) a base encriptada; falha com ``ValidationFailed`` se a chave não servir."""
    conn = sqlcipher3.connect(str(path), check_same_thread=False)
    try:
        # A chave é só hexadecimal gerado por nós; PRAGMA não aceita parâmetros.
        # nosemgrep: formatted-sql-query, sqlalchemy-execute-raw-query
        conn.execute(f"PRAGMA key = \"x'{key.hex()}'\"")
        conn.execute("PRAGMA cipher_compatibility = 4")
        conn.execute("select count(*) from sqlite_master").fetchone()
    except sqlcipher3.DatabaseError as exc:
        conn.close()
        raise ValidationFailed(subcode="wrong_key_or_not_encrypted") from exc
    return conn


def storage_state(path: Path, keys: KeyManager) -> StorageState:
    has_key = keys.get() is not None
    if path.exists() and path.stat().st_size > 0:
        return StorageState.READY if has_key else StorageState.KEY_LOST
    return StorageState.READY if has_key else StorageState.NEW


def open_store(path: Path, keys: KeyManager, dim: int) -> SqliteVectorStore:
    """Abre o índice local; cria a chave só quando ainda não há base nem chave."""
    state = storage_state(path, keys)
    if state is StorageState.KEY_LOST:
        raise ValidationFailed(subcode="key_lost")
    key = keys.get() if state is StorageState.READY else keys.create()
    if key is None:  # só se o keychain mudar entre as duas leituras
        raise ValidationFailed(subcode="key_lost")
    path.parent.mkdir(parents=True, exist_ok=True)
    factory = cast(Callable[[], sqlite3.Connection], lambda: open_encrypted(path, key))
    return SqliteVectorStore(factory, dim)


def reset_index(path: Path, keys: KeyManager) -> None:
    """Reiniciar o índice local: apaga a base e a chave antiga (reindexa-se das pastas)."""
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)
    keys.delete()
