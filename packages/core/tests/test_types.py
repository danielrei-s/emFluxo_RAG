"""Testes de ``rag_core.types`` (contratos C6)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError
from rag_core.types import (
    CLASSIFICATION_RANK,
    ROLE_RANK,
    AccessFilter,
    Acl,
    Answer,
    Block,
    Chunk,
    ChunkMetadata,
    Citation,
    Classification,
    DetectedType,
    Origin,
    Principal,
    Product,
    RawAttachment,
    Role,
    SearchHit,
    SourceFile,
    StructuredDocument,
)

SHA = "a" * 64


def _metadata(**overrides: Any) -> ChunkMetadata:
    fields: dict[str, Any] = {
        "tenant_id": "t1",
        "workspace_id": "w1",
        "doc_id": "d1",
        "source_uri": "upload://d1/a.pdf",
        "content_hash": SHA,
        "doc_hash": SHA,
        "acl": Acl(all_members=True),
        "classification": Classification.INTERNAL,
        "ingested_at": datetime(2026, 1, 1, tzinfo=UTC),
        "parser_version": "1",
        "origin": Origin.CENTRAL,
    }
    fields.update(overrides)
    return ChunkMetadata(**fields)


def _principal(**overrides: Any) -> Principal:
    fields: dict[str, Any] = {
        "tenant_id": "t1",
        "user_id": "u1",
        "role": Role.MEMBER,
        "groups": frozenset({"g1", "g2"}),
        "products": frozenset({Product.WEB}),
    }
    fields.update(overrides)
    return Principal(**fields)


def test_models_are_frozen_and_forbid_extra() -> None:
    acl = Acl()
    with pytest.raises(ValidationError):
        acl.all_members = True
    with pytest.raises(ValidationError):
        Acl(unknown_field=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Block(kind="paragraph", text="x", surprise=True)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        _principal().tenant_id = "t2"


@pytest.mark.parametrize("bad", ["", "abc", "A" * 64, "g" * 64, "a" * 63, "a" * 65])
def test_chunk_metadata_rejects_bad_sha256(bad: str) -> None:
    with pytest.raises(ValidationError):
        _metadata(content_hash=bad)
    with pytest.raises(ValidationError):
        _metadata(doc_hash=bad)


def test_chunk_metadata_accepts_lowercase_sha256() -> None:
    meta = _metadata(content_hash="0123456789abcdef" * 4)
    assert meta.content_hash == "0123456789abcdef" * 4


def test_page_range_validation() -> None:
    with pytest.raises(ValidationError):
        _metadata(page_start=5, page_end=4)
    assert _metadata(page_start=4, page_end=4).page_end == 4
    assert _metadata(page_start=1, page_end=9).page_end == 9
    assert _metadata(page_start=None, page_end=None).page_start is None
    assert _metadata(page_start=3).page_end is None


def test_access_filter_for_principal_copies_fields() -> None:
    principal = _principal(role=Role.EDITOR)
    flt = AccessFilter.for_principal(
        principal,
        origins=frozenset({Origin.CENTRAL, Origin.LOCAL}),
        exclude_local_only=True,
        exclude_classifications=frozenset({Classification.RESTRICTED}),
    )
    assert flt.tenant_id == "t1"
    assert flt.user_id == "u1"
    assert flt.role is Role.EDITOR
    assert flt.groups == frozenset({"g1", "g2"})
    assert flt.origins == frozenset({Origin.CENTRAL, Origin.LOCAL})
    assert flt.exclude_local_only is True
    assert flt.exclude_classifications == frozenset({Classification.RESTRICTED})
    assert flt.workspace_ids is None


def test_access_filter_defaults_are_the_safe_ones() -> None:
    flt = AccessFilter(tenant_id="t", user_id="u", role=Role.VIEWER)
    assert flt.origins == frozenset({Origin.CENTRAL})
    assert flt.exclude_local_only is False
    assert flt.exclude_classifications == frozenset()


def test_structured_document_json_roundtrip_with_attachment_bytes() -> None:
    binary = bytes(range(256))  # não é UTF-8 válido
    doc = StructuredDocument(
        title="Relatório",
        detected_type=DetectedType.EML,
        blocks=(
            Block(kind="heading", text="Título", level=1, page=1),
            Block(
                kind="table",
                text="| a |\n|---|\n| 1 |",
                rows=(("a",), ("1",)),
                flags=frozenset({"ocr"}),
            ),
        ),
        parser_name="p",
        parser_version="1",
        meta={"email_from_domain": "exemplo.pt"},
        warnings=("w",),
        attachments=(RawAttachment(filename="x.bin", data=binary),),
    )
    restored = StructuredDocument.model_validate_json(doc.model_dump_json())
    assert restored == doc
    assert restored.attachments[0].data == binary
    assert restored.blocks[1].rows == (("a",), ("1",))


def test_rank_tables_cover_all_enum_values() -> None:
    assert set(CLASSIFICATION_RANK) == set(Classification)
    assert set(ROLE_RANK) == set(Role)
    assert len(set(CLASSIFICATION_RANK.values())) == len(Classification)
    assert len(set(ROLE_RANK.values())) == len(Role)


def test_rank_tables_are_ordered_by_sensitivity_and_privilege() -> None:
    ranks = [
        CLASSIFICATION_RANK[c]
        for c in (
            Classification.PUBLIC,
            Classification.INTERNAL,
            Classification.CONFIDENTIAL,
            Classification.RESTRICTED,
        )
    ]
    assert ranks == sorted(ranks)
    roles = [
        ROLE_RANK[r]
        for r in (
            Role.VIEWER,
            Role.MEMBER,
            Role.EDITOR,
            Role.ADMIN,
            Role.OWNER,
        )
    ]
    assert roles == sorted(roles)


def test_literal_fields_reject_unknown_values() -> None:
    chunk = Chunk(chunk_id="c", ordinal=0, text="t", metadata=_metadata())
    with pytest.raises(ValidationError):
        SearchHit(chunk=chunk, score=1.0, stage="bogus")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Answer(kind="invented", text="x")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        _principal(aal="aal3")


def test_default_dicts_are_not_shared_between_instances() -> None:
    first = Answer(kind="not_found", text="x")
    second = Answer(kind="not_found", text="y")
    first.timings_ms["total"] = 1  # o dict em si é mutável; só o default não pode ser partilhado
    assert second.timings_ms == {}
    assert (
        StructuredDocument(
            detected_type=DetectedType.TXT, blocks=(), parser_name="p", parser_version="1"
        ).meta
        == {}
    )


def test_source_file_defaults_and_citation_roundtrip() -> None:
    src = SourceFile(
        tenant_id="t",
        workspace_id="w",
        doc_id="d",
        source_uri="file://a.txt",
        filename="a.txt",
        acl=Acl(),
    )
    assert src.classification is Classification.INTERNAL
    assert src.origin is Origin.CENTRAL
    assert src.local_only is False
    cit = Citation(index=1, chunk_id="c", doc_id="d", source_uri="file://a.txt")
    assert Citation.model_validate_json(cit.model_dump_json()) == cit


def test_chunk_metadata_json_roundtrip_keeps_frozensets_and_datetime() -> None:
    meta = _metadata(
        acl=Acl(users=frozenset({"u"}), groups=frozenset({"g"})),
        flags=frozenset({"hidden_text_removed"}),
        heading_path=("A", "B"),
    )
    assert ChunkMetadata.model_validate_json(meta.model_dump_json()) == meta
