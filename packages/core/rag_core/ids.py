"""Identificadores determinísticos e utilitários de hash (C6)."""

from __future__ import annotations

import hashlib
import unicodedata
import uuid


def sha256_hex(data: bytes | str) -> str:
    """SHA-256 em hexadecimal; ``str`` é codificada em UTF-8."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def normalize_rel_path(rel_path: str) -> str:
    """Barra invertida para ``/``, NFC e sem ``./`` inicial (não muda maiúsculas)."""
    path = unicodedata.normalize("NFC", rel_path.replace("\\", "/"))
    while path.startswith("./"):
        path = path[2:]
    return path


def doc_id_local(workspace_id: str, rel_path: str) -> str:
    """ID de documento local, estável entre sistemas operativos."""
    return sha256_hex(f"{workspace_id}:{normalize_rel_path(rel_path)}")[:32]


def child_doc_id(parent_doc_id: str, filename: str) -> str:
    """ID de documento filho (ex.: anexo de email)."""
    return sha256_hex(f"{parent_doc_id}/{filename}")[:32]


def chunk_id(doc_id: str, ordinal: int, content_hash: str) -> str:
    """ID determinístico de chunk; muda com o conteúdo."""
    return sha256_hex(f"{doc_id}:{ordinal}:{content_hash}")[:32]


def new_id() -> str:
    """Novo identificador aleatório (UUID v4 como string)."""
    return str(uuid.uuid4())
