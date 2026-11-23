"""Testes de F11-T02: índice local encriptado e chave no keychain (INV-13)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from keyring_fixture import MemoryKeyring
from rag_core.errors import ValidationFailed
from rag_core.fakes import FakeEmbedder
from rag_core.testing.chunks import make_chunk
from rag_local.keys import KeyManager, KeyUnavailableError
from rag_local.storage import (
    StorageState,
    open_encrypted,
    open_store,
    reset_index,
    storage_state,
)

pytest_plugins = ("keyring_fixture",)
DIM = FakeEmbedder().dim


def test_db_file_is_not_plain_sqlite(tmp_path: Path, memory_keyring: MemoryKeyring) -> None:
    path = tmp_path / "indice.db"
    store = open_store(path, KeyManager("p1"), DIM)
    store.upsert([make_chunk("texto secreto CANARIO", doc_id="a")])
    del store
    raw = path.read_bytes()
    assert not raw.startswith(b"SQLite format 3") and b"CANARIO" not in raw
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(str(path)).execute("select * from sqlite_master").fetchall()


def test_wrong_key_fails(tmp_path: Path, memory_keyring: MemoryKeyring) -> None:
    path = tmp_path / "indice.db"
    open_store(path, KeyManager("p1"), DIM)
    with pytest.raises(ValidationFailed) as exc:
        open_encrypted(path, bytes(32))
    assert exc.value.subcode == "wrong_key_or_not_encrypted"
    plain = tmp_path / "simples.db"
    connection = sqlite3.connect(str(plain))
    connection.execute("create table t (a)")
    connection.commit()
    connection.close()
    with pytest.raises(ValidationFailed):
        open_encrypted(plain, KeyManager("x").create())


def test_key_lost_does_not_overwrite_db(tmp_path: Path, memory_keyring: MemoryKeyring) -> None:
    path = tmp_path / "indice.db"
    keys = KeyManager("p1")
    assert storage_state(path, keys) is StorageState.NEW
    open_store(path, keys, DIM)
    assert storage_state(path, keys) is StorageState.READY
    before = path.read_bytes()
    keys.delete()  # o keychain perdeu a chave
    assert storage_state(path, keys) is StorageState.KEY_LOST
    with pytest.raises(ValidationFailed) as exc:
        open_store(path, keys, DIM)
    assert exc.value.subcode == "key_lost"
    assert keys.get() is None and path.read_bytes() == before  # nada foi criado nem mexido
    reset_index(path, keys)  # só o "reiniciar" explícito recomeça
    assert not path.exists()
    assert storage_state(path, keys) is StorageState.NEW
    open_store(path, keys, DIM)
    assert keys.get() is not None


def test_key_manager_rules(memory_keyring: MemoryKeyring) -> None:
    keys = KeyManager("p1")
    assert keys.get() is None
    key = keys.create()
    assert len(key) == 32 and keys.get() == key
    with pytest.raises(KeyUnavailableError, match="key_exists"):
        keys.create()
    assert KeyManager("p2").get() is None  # perfis independentes
    assert ("rag-local", "db-key:p1") in memory_keyring.items
    keys.delete()
    keys.delete()  # apagar duas vezes não falha
    assert keys.get() is None


def test_fts5_available_or_fallback_used(tmp_path: Path, memory_keyring: MemoryKeyring) -> None:
    store = open_store(tmp_path / "i.db", KeyManager("p1"), DIM)
    assert store.keyword_backend in {"fts5", "memory"}
    store.upsert([make_chunk("orçamento anual", doc_id="a")])
