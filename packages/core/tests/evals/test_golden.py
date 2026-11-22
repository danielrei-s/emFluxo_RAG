"""Validação do golden set v0 contra o manifest do corpus (C11)."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError
from rag_core.evals import GoldenItem, load_golden
from rag_core.evals.golden import GOLDEN_DIR, load_all_golden
from rag_core.testing import corpus

MINIMUMS = {
    "answerable_single": 20,
    "answerable_table": 4,
    "multi_doc": 3,
    "unanswerable": 6,
    "acl_probe": 4,
    "cross_tenant": 3,
    "injection": 3,
    "followup": 2,
    "general_knowledge": 2,
}
ITEMS = load_all_golden()
DOCS = {d["id"]: d for d in corpus.load_manifest()["documents"]}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def test_golden_schema_valid() -> None:
    assert len(ITEMS) >= 55
    ids = [i.id for i in ITEMS]
    assert len(ids) == len(set(ids))
    for path in sorted(GOLDEN_DIR.glob("*.yaml")):
        assert load_golden(path)
    item = GoldenItem(id="X", tenant="aurora", user="ana", question="?", category="unanswerable")
    assert item.expected_kind == "grounded"
    assert item.history is None
    with pytest.raises(ValidationError):
        GoldenItem(id="X", tenant="aurora", user="ana", question="?", category="inventada")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        GoldenItem(  # type: ignore[call-arg]
            id="X", tenant="a", user="u", question="?", category="multi_doc", extra=1
        )


def test_expected_docs_exist_in_manifest_and_tenant_matches() -> None:
    for item in ITEMS:
        for doc_id in item.expected_doc_ids:
            assert doc_id in DOCS, (item.id, doc_id)
            assert DOCS[doc_id]["tenant"] == item.tenant, (item.id, doc_id)
        if item.expected_kind == "grounded":
            assert item.expected_doc_ids, item.id
            assert item.expected_answer_contains, item.id
        else:
            assert not item.expected_answer_contains, item.id


def test_expected_strings_come_from_manifest_facts() -> None:
    for item in ITEMS:
        facts = _norm(" ".join(f for d in item.expected_doc_ids for f in DOCS[d]["facts"]))
        for needle in item.expected_answer_contains:
            assert _norm(needle) in facts, (item.id, needle)
    canaries = corpus.all_canaries()
    for item in ITEMS:
        if item.category in {"cross_tenant", "injection"}:
            assert any(m in canaries for m in item.must_not_contain), item.id


def test_category_minimums() -> None:
    counts: Counter[str] = Counter(i.category for i in ITEMS)
    for category, minimum in MINIMUMS.items():
        assert counts[category] >= minimum, (category, counts[category])
    assert set(counts) == set(MINIMUMS)
    assert sum(1 for i in ITEMS if i.category == "followup" and i.history) >= 2
    assert all(i.history for i in ITEMS if i.category == "followup")
    kinds = {i.expected_kind for i in ITEMS if i.category == "general_knowledge"}
    assert kinds == {"general_knowledge"}
    assert {i.expected_kind for i in ITEMS if i.category == "unanswerable"} == {"not_found"}


def test_users_exist_for_tenant() -> None:
    tenants = corpus.load_manifest()["tenants"]
    for item in ITEMS:
        assert item.tenant in tenants, item.id
        assert item.user in {u["id"] for u in tenants[item.tenant]["users"]}, item.id
        assert item.id.startswith("A-" if item.tenant == "aurora" else "B-"), item.id


def test_acl_probes_cover_the_c11_cases() -> None:
    probes = {i.id: i for i in ITEMS if i.category == "acl_probe"}
    by_user = {(i.user, i.expected_kind) for i in probes.values()}
    assert ("carla", "not_found") in by_user  # admin não vê salários sem o grupo rh
    assert ("rui", "grounded") in by_user
    assert Path(GOLDEN_DIR).name == "golden"
