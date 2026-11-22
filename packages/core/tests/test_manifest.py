"""Testes do ``CorpusManifest`` (usado pela CLI e pelos testes)."""

from __future__ import annotations

import pytest
from rag_core.manifest import DEFAULT_TENANT, CorpusManifest
from rag_core.testing import corpus
from rag_core.types import Classification, Role

MANIFEST = CorpusManifest(corpus.load_manifest())


def test_default_manifest_has_a_dev_owner_and_nothing_else() -> None:
    empty = CorpusManifest()
    owner = empty.principal_for(DEFAULT_TENANT, "dev")
    assert owner.role == Role.OWNER and owner.groups == frozenset()
    assert owner == empty.principal_for(DEFAULT_TENANT, "dev")
    assert empty.tenant_id("dev") == owner.tenant_id
    with pytest.raises(KeyError):
        empty.tenant_id("aurora")
    with pytest.raises(KeyError):
        empty.principal_for("aurora", "ana")


def test_ids_are_the_same_as_the_corpus_helpers() -> None:
    assert MANIFEST.tenant_id("aurora") == corpus.tenant_id("aurora")
    assert MANIFEST.principal_for("aurora", "rui") == corpus.principal_for("aurora", "rui")
    assert MANIFEST.source_for_id("A07") == corpus.source_file_for("A07")
    assert MANIFEST.doc_uuid("A07") == corpus.source_file_for("A07").doc_id
    assert MANIFEST.workspace_id("aurora") == corpus.source_file_for("A07").workspace_id
    assert MANIFEST.workspace_id("aurora", "outro") != MANIFEST.workspace_id("aurora")


def test_source_for_file_uses_manifest_acl_when_the_file_is_known() -> None:
    known = MANIFEST.source_for_file(
        "aurora", "default", "aurora/rh_salarios_2026.xlsx", "rh_salarios_2026.xlsx"
    )
    assert known.doc_id == corpus.source_file_for("A07").doc_id
    assert known.acl.groups == frozenset({"rh"})
    assert known.classification == Classification.RESTRICTED
    assert known.source_uri == "file://aurora/rh_salarios_2026.xlsx"

    unknown = MANIFEST.source_for_file("aurora", "default", "novo\\relatorio.txt", "relatorio.txt")
    assert unknown.acl.all_members is True
    assert unknown.classification == Classification.INTERNAL
    assert unknown.source_uri == "file://novo/relatorio.txt"
    same_path = MANIFEST.source_for_file("aurora", "default", "novo/relatorio.txt", "relatorio.txt")
    assert same_path.doc_id == unknown.doc_id  # estável entre sistemas operativos
    assert MANIFEST.entry_by_filename("boreal", "rh_salarios_2026.xlsx") is None
    with pytest.raises(KeyError):
        MANIFEST.entry_by_id("Z99")
