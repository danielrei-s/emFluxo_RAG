"""Gate da F3: factos do manifest nos chunks e canários ocultos fora do índice."""

from __future__ import annotations

import re

from rag_core.testing import corpus

from .conftest import IngestedCorpus


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_every_manifest_fact_in_some_chunk(ingested_corpus: IngestedCorpus) -> None:
    """Todos os factos aparecem em chunks do tenant certo (A10 precisa de OCR: excluído)."""
    ids_by_doc = {
        d["id"]: [r.doc_id for r in ingested_corpus.results[d["id"]]]
        for d in corpus.load_manifest()["documents"]
    }
    for doc in corpus.load_manifest()["documents"]:
        if doc["id"] == "A10":
            continue
        own_ids = set(ids_by_doc[doc["id"]])  # o próprio e os anexos
        text = _squash(
            " ".join(c.text for c in ingested_corpus.store.upserted if c.metadata.doc_id in own_ids)
        )
        for fact in doc["facts"]:
            assert _squash(fact) in text, (doc["id"], fact)


def test_inv06_hidden_canaries_never_indexed(ingested_corpus: IngestedCorpus) -> None:
    everything = "\n".join(c.text for c in ingested_corpus.store.upserted)
    for canary in ("HIDDEN-5521", "HIDDEN-HTML-3310", "HIDDEN-SHEET-4410"):
        assert canary not in everything
    assert "INSTRUÇÃO OCULTA" not in everything
    assert "0000" not in everything or "código é 0000" not in everything


def test_visible_canaries_are_indexed_with_their_acl(ingested_corpus: IngestedCorpus) -> None:
    by_doc = {c.metadata.doc_id: c for c in ingested_corpus.store.upserted}
    salaries = by_doc[corpus.source_file_for("A07").doc_id]
    assert "CANARIO-RH-91C2" in salaries.text
    assert salaries.metadata.acl.groups == frozenset({"rh"})
    assert salaries.metadata.classification.value == "restricted"
    tenant_b = by_doc[corpus.source_file_for("B01").doc_id]
    assert tenant_b.metadata.tenant_id == corpus.tenant_id("boreal")
