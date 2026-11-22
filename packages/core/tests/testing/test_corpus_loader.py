"""Testes do carregador do corpus sintético (``rag_core.testing.corpus``)."""

from __future__ import annotations

import pytest
from rag_core.ids import sha256_hex
from rag_core.testing import corpus
from rag_core.types import Classification, Role


def test_corpus_loader_builds_principals_and_sources() -> None:
    manifest = corpus.load_manifest()
    assert {d["id"] for d in manifest["documents"]} >= {"A01", "B02"}

    carla = corpus.principal_for("aurora", "carla")
    assert carla.role == Role.ADMIN
    assert carla.groups == frozenset({"direcao"})
    assert carla.tenant_id == corpus.tenant_id("aurora")
    assert carla == corpus.principal_for("aurora", "carla")  # IDs estáveis
    assert carla.user_id != corpus.principal_for("aurora", "ana").user_id
    assert corpus.principal_for("boreal", "bruno").tenant_id != carla.tenant_id

    a07 = corpus.source_file_for("A07")
    assert a07.classification == Classification.RESTRICTED
    assert a07.acl.groups == frozenset({"rh"})
    assert a07.acl.all_members is False
    assert a07.filename == "rh_salarios_2026.xlsx"
    assert a07.tenant_id == corpus.tenant_id("aurora")
    assert a07.source_uri == f"upload://{a07.doc_id}/rh_salarios_2026.xlsx"
    assert corpus.source_file_for("A01").acl.all_members is True
    assert corpus.source_file_for("A01").doc_id != a07.doc_id

    entry = next(d for d in manifest["documents"] if d["id"] == "A07")
    assert sha256_hex(corpus.read_bytes("A07")) == entry["sha256"]


def test_all_canaries_include_every_manifest_canary() -> None:
    canaries = corpus.all_canaries()
    assert {"CANARIO-RH-91C2", "CANARIO-TENANT-B-7F3A", "PWNED-7781", "HIDDEN-5521"} <= canaries
    assert isinstance(canaries, frozenset)


def test_unknown_ids_raise() -> None:
    with pytest.raises(KeyError):
        corpus.source_file_for("Z99")
    with pytest.raises(KeyError):
        corpus.principal_for("aurora", "ninguem")
    with pytest.raises(KeyError):
        corpus.principal_for("nada", "ana")
