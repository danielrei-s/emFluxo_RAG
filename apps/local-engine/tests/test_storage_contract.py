"""O contrato do VectorStore aplicado ao índice local encriptado (F11-T02)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import keyring
from keyring_fixture import MemoryKeyring
from rag_core.fakes import FakeEmbedder
from rag_core.interfaces import VectorStore
from rag_local.keys import KeyManager
from rag_local.storage import open_store

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "core"))
from tests.contract.vectorstore_contract import VectorStoreContract

DIM = FakeEmbedder().dim


class TestEncryptedStoreContract(VectorStoreContract):
    supports_local_origin = True

    def make_store(self) -> VectorStore:
        keyring.set_keyring(MemoryKeyring())
        path = Path(tempfile.mkdtemp()) / "indice.db"
        return open_store(path, KeyManager("contrato"), DIM)
