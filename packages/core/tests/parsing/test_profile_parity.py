"""Testes de F3-T09: os perfis lite e full extraem os mesmos factos do corpus."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from rag_core.ingestion.detect import sniff
from rag_core.interfaces import ParseLimits
from rag_core.parsing.lite import lite_registry
from rag_core.parsing.registry import ParserRegistry
from rag_core.testing import corpus

PARITY_DOCS = ["A01", "A02", "A03", "A04", "A05", "A06", "A07", "A11", "A12", "A13"]
LIMITS = ParseLimits()
ARTIFACTS = corpus.CORPUS_DIR.parents[1] / ".docling-artifacts"  # fora do git (.gitignore)
PROFILES = ["lite", pytest.param("full", marks=pytest.mark.docling)]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def registry_for(profile: str) -> ParserRegistry:
    if profile == "lite":
        return lite_registry()
    from rag_core.parsing.docling_full import full_registry

    return full_registry(ARTIFACTS)


def full_text(registry: ParserRegistry, data: bytes, filename: str) -> str:
    """Texto de um documento e, recursivamente, dos seus anexos."""
    detected, _ = sniff(data, filename, LIMITS)
    doc = registry.get(detected).parse(data, filename=filename, detected=detected, limits=LIMITS)
    parts = [b.text for b in doc.blocks]
    parts += [full_text(registry, a.data, a.filename) for a in doc.attachments]
    return _squash(" ".join(parts))


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("doc_id", PARITY_DOCS)
def test_profile_parity_facts(profile: str, doc_id: str) -> None:
    entry = next(d for d in corpus.load_manifest()["documents"] if d["id"] == doc_id)
    text = full_text(registry_for(profile), corpus.read_bytes(doc_id), Path(entry["file"]).name)
    for fact in entry["facts"]:
        assert _squash(fact) in text, (profile, doc_id, fact)
