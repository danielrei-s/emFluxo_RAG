"""Testes de F3-T13: serviço de ingestão incremental."""

from __future__ import annotations

import email
import email.policy
import io
import zipfile
from collections.abc import Sequence
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest
from rag_core.clock import FakeClock
from rag_core.config import ChunkingSettings, Settings
from rag_core.fakes import FakeEmbedder, InMemoryVectorStore
from rag_core.ids import child_doc_id
from rag_core.ingestion.pipeline import EMBED_BATCH_SIZE, IngestionService
from rag_core.interfaces import ParseLimits
from rag_core.logging import ALLOWED_KEYS
from rag_core.parsing.lite import lite_registry
from rag_core.testing import assert_no_canary, corpus
from rag_core.testing.corpus import tenant_id
from rag_core.types import AccessFilter, Origin, Role, SourceFile, StructuredDocument

from .conftest import IngestedCorpus

TENANT = tenant_id("aurora")
FLT = AccessFilter(tenant_id=TENANT, user_id="u", role=Role.OWNER, groups=frozenset())


def inproc_runner(data: bytes, **kwargs: Any) -> StructuredDocument:
    """Runner rápido para testes de lógica: parseia no próprio processo (sem sandbox)."""
    detected = kwargs["detected"]
    return (
        lite_registry()
        .get(detected)
        .parse(data, filename=kwargs["filename"], detected=detected, limits=kwargs["limits"])
    )


class CountingEmbedder(FakeEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.batches: list[int] = []

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.batches.append(len(texts))
        return super().embed_documents(texts)


def _service(
    store: InMemoryVectorStore | None = None,
    embedder: FakeEmbedder | None = None,
    **kwargs: Any,
) -> tuple[IngestionService, InMemoryVectorStore]:
    store = store or InMemoryVectorStore()
    kwargs.setdefault("runner", inproc_runner)
    kwargs.setdefault("settings", Settings.for_tests())
    service = IngestionService(
        embedder=embedder or FakeEmbedder(), store=store, clock=FakeClock(), **kwargs
    )
    return service, store


def _source(name: str = "nota.txt", doc_id: str = "doc-1", **overrides: Any) -> SourceFile:
    base = corpus.source_file_for("A11").model_copy(
        update={"doc_id": doc_id, "filename": name, "source_uri": f"upload://{doc_id}/{name}"}
    )
    return base.model_copy(update=overrides)


def _kw(store: InMemoryVectorStore, query: str) -> list[str]:
    return [h.chunk.text for h in store.search_keyword(query, flt=FLT, k=20)]


def _eml(subject: str, attachments: list[tuple[str, bytes]] | None = None) -> bytes:
    msg = EmailMessage()
    msg["From"] = "a@exemplo.pt"
    msg["To"] = "b@exemplo.pt"
    msg["Subject"] = subject
    msg.set_content(f"Corpo do email {subject} com texto suficiente para ser indexado.")
    for name, payload in attachments or []:
        if name.endswith(".eml"):
            inner = email.message_from_bytes(payload, policy=email.policy.default)
            msg.add_attachment(inner, filename=name)
        else:
            msg.add_attachment(payload, maintype="text", subtype="plain", filename=name)
    return msg.as_bytes()


# --------------------------------------------------------- corpus (sandbox real)


def test_ingest_aurora_corpus_statuses(ingested_corpus: IngestedCorpus) -> None:
    results = ingested_corpus.results
    for doc in corpus.load_manifest()["documents"]:
        doc_id = doc["id"]
        parent = results[doc_id][0]
        if doc_id == "A10":  # só imagem: sem OCR não há texto
            assert (parent.status, parent.error_code) == (
                "failed",
                "validation_failed:no_text_extracted",
            )
        else:
            assert parent.status == "indexed", (doc_id, parent)
            assert parent.chunk_count >= 1
    expected_invalid = {
        "encrypted.pdf": "encrypted_file",
        "truncated.pdf": "corrupted_file",
        "not_really.docx": "corrupted_file",
        "zip_bomb.docx": "validation_failed:zip_bomb",
        "macro_template.docm": "corrupted_file",
        "random.bin": "unsupported_type",
    }
    for name, code in expected_invalid.items():
        (result,) = results[f"invalid/{name}"]
        assert (result.status, result.error_code) == ("failed", code), name


def test_email_attachment_indexed_as_child(ingested_corpus: IngestedCorpus) -> None:
    parent, child = ingested_corpus.results["A06"]
    source = corpus.source_file_for("A06")
    assert child.doc_id == child_doc_id(source.doc_id, "condicoes.pdf")
    assert (parent.status, child.status) == ("indexed", "indexed")
    chunks = [c for c in ingested_corpus.store.upserted if c.metadata.doc_id == child.doc_id]
    assert any("portes grátis" in c.text for c in chunks)
    assert chunks[0].metadata.acl == source.acl
    assert chunks[0].metadata.classification == source.classification
    assert chunks[0].metadata.source_uri == f"upload://{child.doc_id}/condicoes.pdf"
    assert all(c.embedding is not None for c in ingested_corpus.store.upserted)


def test_inv03_ingestion_logs_have_no_content(
    captured_logs: list[dict[str, Any]], tmp_path: Path
) -> None:
    service, _ = _service()
    for doc_id in ("A03", "A07", "A08", "A09", "A12", "B01"):
        name = corpus.source_file_for(doc_id).filename
        service.ingest_file(
            corpus.source_file_for(doc_id).model_copy(update={"filename": name}),
            corpus.read_bytes(doc_id),
        )
    service.ingest_file(
        corpus.invalid_source("encrypted.pdf"), corpus.read_invalid("encrypted.pdf")
    )
    service.ingest_file(corpus.source_file_for("A07"), corpus.read_bytes("A07"))  # unchanged
    assert captured_logs
    assert_no_canary(str(captured_logs))
    for event in captured_logs:
        assert set(event) - {"event", "level", "timestamp", "ts", "service"} <= ALLOWED_KEYS
    events = {e["event"] for e in captured_logs}
    assert {"ingestion.indexed", "ingestion.failed", "ingestion.unchanged"} <= events


# ------------------------------------------------------------------ incremental


def test_reingest_unchanged_is_noop() -> None:
    embedder = CountingEmbedder()
    service, store = _service(embedder=embedder)
    source, data = _source(), b"O prazo de pagamento e de trinta dias.\n"
    first = service.ingest_file(source, data)
    batches = list(embedder.batches)
    second = service.ingest_file(source, data)
    assert [r.status for r in first] == ["indexed"]
    assert [r.status for r in second] == ["unchanged"]
    assert embedder.batches == batches  # nada foi re-embebido
    assert len(_kw(store, "pagamento")) == 1


def test_modified_file_reindexed_and_old_chunks_removed() -> None:
    service, store = _service()
    source = _source()
    service.ingest_file(source, b"Versao antiga com palavra obsoleta aqui.")
    assert _kw(store, "obsoleta")
    (result,) = service.ingest_file(source, b"Versao nova com palavra atualizada aqui.")
    assert result.status == "indexed"
    assert _kw(store, "obsoleta") == []
    assert _kw(store, "atualizada")
    assert len(store.document_hashes(source.tenant_id, source.workspace_id)) == 1


def test_failed_reingest_keeps_the_previous_version() -> None:
    service, store = _service()
    source = _source("relatorio.docx")
    docx = corpus.read_bytes("A02")
    assert service.ingest_file(source, docx)[0].status == "indexed"
    (result,) = service.ingest_file(source, b"isto ja nao e um docx")
    assert (result.status, result.error_code) == ("failed", "corrupted_file")
    assert _kw(store, "quilometragem")  # a versão anterior continua pesquisável


def test_empty_document_fails_with_no_text() -> None:
    service, _ = _service()
    (result,) = service.ingest_file(_source(), b"   \n\n  ")
    assert result.error_code == "validation_failed:no_text_extracted"


def test_embeddings_are_computed_in_batches_of_32() -> None:
    embedder = CountingEmbedder()
    cfg = ChunkingSettings(target_tokens=20, min_tokens=8, max_tokens=40, overlap_ratio=0.0)
    service, _ = _service(embedder=embedder, settings=Settings.for_tests(chunking=cfg))
    text = "\n\n".join(
        f"Parágrafo número {n} com um texto de enchimento razoável aqui." for n in range(150)
    )
    (result,) = service.ingest_file(_source(), text.encode())
    assert result.chunk_count > 2 * EMBED_BATCH_SIZE
    assert embedder.batches[:-1] == [EMBED_BATCH_SIZE] * (len(embedder.batches) - 1)
    assert sum(embedder.batches) == result.chunk_count


def test_warnings_from_sniff_and_parser_are_reported() -> None:
    service, _ = _service()
    macro = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(corpus.read_bytes("A02"))) as src,
        zipfile.ZipFile(macro, "w", zipfile.ZIP_DEFLATED) as dst,
    ):
        for item in src.infolist():
            dst.writestr(item, src.read(item))
        dst.writestr("word/vbaProject.bin", b"macro")
    (with_macro,) = service.ingest_file(_source("m.docx", "d-macro"), macro.getvalue())
    assert with_macro.warnings == ("has_macros",)
    (hidden,) = service.ingest_file(_source("a09.docx", "d-hidden"), corpus.read_bytes("A09"))
    assert hidden.warnings == ("hidden_text_removed",)


def test_profile_and_limits_reach_the_runner() -> None:
    seen: dict[str, Any] = {}

    def spy(data: bytes, **kwargs: Any) -> StructuredDocument:
        seen.update(kwargs)
        return inproc_runner(data, **kwargs)

    limits = ParseLimits(max_pages=3)
    service, _ = _service(
        runner=spy, registry_profile="full", limits=limits, artifacts_path=Path("x")
    )
    service.ingest_file(_source(), b"Texto simples para o teste do runner.")
    assert (seen["profile"], seen["limits"], seen["artifacts_path"]) == ("full", limits, Path("x"))


# -------------------------------------------------------------------- anexos


def test_attachment_recursion_stops_at_depth_two() -> None:
    inner = _eml("nivel 3")
    middle = _eml("nivel 2", [("terceiro.eml", inner)])
    top = _eml("nivel 1", [("segundo.eml", middle), ("nota.txt", b"Anexo de texto simples aqui.")])
    service, store = _service()
    source = _source("topo.eml", "doc-top")
    results = service.ingest_file(source, top)
    child = child_doc_id("doc-top", "segundo.eml")
    grandchild = child_doc_id(child, "terceiro.eml")
    note = child_doc_id("doc-top", "nota.txt")
    assert [(r.doc_id, r.status) for r in results] == [
        ("doc-top", "indexed"),
        (child, "indexed"),
        (grandchild, "indexed"),
        (note, "indexed"),
    ]
    assert set(store.document_hashes(source.tenant_id, source.workspace_id)) == {
        "doc-top", child, grandchild, note,
    }  # fmt: skip
    deeper = _eml("nivel 4")
    nested = _eml("a", [("b.eml", _eml("b", [("c.eml", _eml("c", [("d.eml", deeper)]))]))])
    results = service.ingest_file(_source("n.eml", "doc-n"), nested)
    assert len(results) == 3  # o quarto nível não é ingerido


def test_child_inherits_origin_and_uses_file_uri_for_local_sources() -> None:
    service, store = _service()
    source = _source("m.eml", "doc-local", origin=Origin.LOCAL, source_uri="file://pasta/m.eml")
    service.ingest_file(source, _eml("local", [("a.txt", b"Texto do anexo local aqui.")]))
    child_id = child_doc_id("doc-local", "a.txt")
    chunk = next(
        h.chunk
        for h in store.search_keyword(
            "anexo", flt=FLT.model_copy(update={"origins": frozenset({Origin.LOCAL})}), k=5
        )
        if h.chunk.metadata.doc_id == child_id
    )
    assert chunk.metadata.source_uri == "file://pasta/m.eml#a.txt"
    assert chunk.metadata.origin == Origin.LOCAL


def test_delete_removes_children_and_stale_attachments_are_dropped() -> None:
    service, store = _service()
    source = _source("m.eml", "doc-m")
    child_id = child_doc_id("doc-m", "a.txt")
    service.ingest_file(source, _eml("com anexo", [("a.txt", b"Conteudo do anexo unico aqui.")]))
    assert child_id in store.document_hashes(source.tenant_id, source.workspace_id)

    service.ingest_file(source, _eml("sem anexo"))  # reingestão sem o anexo
    hashes = store.document_hashes(source.tenant_id, source.workspace_id)
    assert set(hashes) == {"doc-m"}

    service.ingest_file(source, _eml("outra vez", [("a.txt", b"Conteudo do anexo unico aqui.")]))
    results = service.delete(source.tenant_id, "doc-m")
    assert {r.doc_id for r in results} == {"doc-m", child_id}
    assert all(r.status == "deleted" for r in results)
    assert store.document_hashes(source.tenant_id, source.workspace_id) == {}


# ---------------------------------------------------------------- sincronização


def test_inv18_removed_file_deleted_from_store() -> None:
    service, store = _service()
    a, b = _source("a.txt", "doc-a"), _source("b.txt", "doc-b")
    entries = {
        "a.txt": (a, lambda: b"Primeiro ficheiro com texto unico alfa.", "ha"),
        "b.txt": (b, lambda: b"Segundo ficheiro com texto unico beta.", "hb"),
    }
    first = service.sync_workspace(a.tenant_id, a.workspace_id, entries)
    assert sorted(r.status for r in first) == ["indexed", "indexed"]
    assert _kw(store, "beta")

    results = service.sync_workspace(a.tenant_id, a.workspace_id, {"a.txt": entries["a.txt"]})
    assert [(r.doc_id, r.status) for r in results if r.status == "deleted"] == [
        ("doc-b", "deleted")
    ]
    assert _kw(store, "beta") == []
    assert "doc-b" not in store.document_hashes(a.tenant_id, a.workspace_id)


def test_sync_adds_changes_and_skips_unchanged_without_reading() -> None:
    from rag_core.ids import sha256_hex

    service, store = _service()
    reads: list[str] = []

    def reader(name: str, content: bytes) -> Any:
        def read() -> bytes:
            reads.append(name)
            return content

        return read

    def entry(name: str, content: bytes) -> tuple[SourceFile, Any, str]:
        return _source(name, f"doc-{name}"), reader(name, content), sha256_hex(content)

    v1 = {"a": entry("a.txt", b"Ficheiro a versao um."), "b": entry("b.txt", b"Ficheiro b igual.")}
    service.sync_workspace(TENANT, v1["a"][0].workspace_id, v1)
    reads.clear()
    v2 = {
        "a": entry("a.txt", b"Ficheiro a versao dois alterada."),
        "b": v1["b"],
        "c": entry("c.txt", b"Ficheiro c novo."),
    }
    results = service.sync_workspace(TENANT, v1["a"][0].workspace_id, v2)
    by_doc = {r.doc_id: r.status for r in results}
    assert by_doc == {"doc-a.txt": "indexed", "doc-b.txt": "unchanged", "doc-c.txt": "indexed"}
    assert sorted(reads) == ["a.txt", "c.txt"]  # o b não foi lido
    assert _kw(store, "alterada")
    assert _kw(store, "um") == []  # a versão um desapareceu


def test_sync_keeps_attachments_of_wanted_documents_and_removes_them_with_the_parent() -> None:
    from rag_core.ids import sha256_hex

    service, store = _service()
    raw = _eml("pai", [("a.txt", b"Conteudo do anexo do pai aqui.")])
    source = _source("pai.eml", "doc-pai")
    entry = {"p": (source, lambda: raw, sha256_hex(raw))}
    service.sync_workspace(source.tenant_id, source.workspace_id, entry)
    again = service.sync_workspace(source.tenant_id, source.workspace_id, entry)
    assert [r.status for r in again] == ["unchanged"]
    assert (
        len(store.document_hashes(source.tenant_id, source.workspace_id)) == 2
    )  # filho preservado
    final = service.sync_workspace(source.tenant_id, source.workspace_id, {})
    assert {r.doc_id for r in final} == {"doc-pai", child_doc_id("doc-pai", "a.txt")}
    assert store.document_hashes(source.tenant_id, source.workspace_id) == {}


def test_errors_never_stop_the_batch() -> None:
    service, store = _service()

    def unreadable() -> bytes:
        raise OSError("sem permissão")

    entries = {
        "mau": (_source("mau.docx", "doc-mau"), lambda: b"nao sou docx", "h1"),
        "ilegivel": (_source("x.txt", "doc-x"), unreadable, "h2"),
        "bom": (_source("bom.txt", "doc-bom"), lambda: b"Texto bom e valido para indexar.", "h3"),
    }
    results = service.sync_workspace(TENANT, entries["bom"][0].workspace_id, entries)
    by_doc = {r.doc_id: (r.status, r.error_code) for r in results}
    assert by_doc == {
        "doc-mau": ("failed", "corrupted_file"),
        "doc-x": ("failed", "read_failed"),
        "doc-bom": ("indexed", None),
    }
    assert _kw(store, "valido")


def test_default_clock_and_counter_are_used_when_omitted() -> None:
    store = InMemoryVectorStore()
    service = IngestionService(
        embedder=FakeEmbedder(), store=store, settings=Settings.for_tests(), runner=inproc_runner
    )
    (result,) = service.ingest_file(_source(), b"Texto com relogio e contador por omissao.")
    assert result.status == "indexed"
    chunk = store.search_keyword("relogio", flt=FLT, k=1)[0].chunk
    assert chunk.metadata.ingested_at.tzinfo is not None
    assert chunk.embedding_model == FakeEmbedder().model_id


def test_real_sandbox_path_is_the_default() -> None:
    from rag_core.ingestion.sandbox import run_parser_sandboxed

    service = IngestionService(
        embedder=FakeEmbedder(), store=InMemoryVectorStore(), settings=Settings.for_tests()
    )
    assert service._runner is run_parser_sandboxed


def test_invalid_source_rejects_unknown_files() -> None:
    with pytest.raises(KeyError):
        corpus.invalid_source("nao-existe.bin")
