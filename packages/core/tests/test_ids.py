"""Testes de ``rag_core.ids``."""

from __future__ import annotations

import hashlib
import re
import unicodedata

from rag_core import ids


def test_sha256_hex_accepts_str_and_bytes() -> None:
    expected = hashlib.sha256("ação".encode()).hexdigest()
    assert ids.sha256_hex("ação") == expected
    assert ids.sha256_hex("ação".encode()) == expected


def test_normalize_rel_path_converts_separators_and_strips_leading_dot_slash() -> None:
    assert ids.normalize_rel_path(r".\a\b.pdf") == "a/b.pdf"
    assert ids.normalize_rel_path("./a/b.pdf") == "a/b.pdf"


def test_normalize_rel_path_keeps_case() -> None:
    assert ids.normalize_rel_path("A/B.PDF") == "A/B.PDF"


def test_chunk_id_is_deterministic_and_changes_with_content() -> None:
    first = ids.chunk_id("doc1", 0, "hash-a")
    assert first == ids.chunk_id("doc1", 0, "hash-a")
    assert first != ids.chunk_id("doc1", 0, "hash-b")
    assert first != ids.chunk_id("doc1", 1, "hash-a")
    assert first == hashlib.sha256(b"doc1:0:hash-a").hexdigest()[:32]


def test_doc_id_local_normalizes_windows_paths() -> None:
    assert ids.doc_id_local("ws", r"a\b.pdf") == ids.doc_id_local("ws", "a/b.pdf")


def test_doc_id_local_nfc_normalization() -> None:
    nfc = unicodedata.normalize("NFC", "ação.pdf")
    nfd = unicodedata.normalize("NFD", "ação.pdf")
    assert nfc != nfd
    assert ids.doc_id_local("ws", nfd) == ids.doc_id_local("ws", nfc)


def test_doc_id_local_depends_on_workspace() -> None:
    assert ids.doc_id_local("ws1", "a.pdf") != ids.doc_id_local("ws2", "a.pdf")
    assert len(ids.doc_id_local("ws1", "a.pdf")) == 32


def test_child_doc_id_matches_contract() -> None:
    assert ids.child_doc_id("parent", "x.txt") == hashlib.sha256(b"parent/x.txt").hexdigest()[:32]


def test_new_id_is_unique_uuid_string() -> None:
    a, b = ids.new_id(), ids.new_id()
    assert a != b
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}", a)
