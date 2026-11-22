"""Testes de F2-T01: o corpus sintético commitado é consistente com o ``manifest.yaml``."""

from __future__ import annotations

import email
import hashlib
import io
import re
import zipfile
from email import policy
from pathlib import Path
from typing import Any

import pytest
import yaml
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation
from pypdf import PdfReader

CORPUS = Path(__file__).resolve().parents[2] / "fixtures" / "corpus"
MANIFEST: dict[str, Any] = yaml.safe_load((CORPUS / "manifest.yaml").read_text(encoding="utf-8"))
DOCS: list[dict[str, Any]] = MANIFEST["documents"]
INVALID: list[dict[str, Any]] = MANIFEST["invalid"]
CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _pdf_pages(data: bytes) -> list[str]:
    return [_squash(p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages]


def _docx_text(path: Path) -> str:
    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        parts += [cell.text for row in table.rows for cell in row.cells]
    return _squash(" ".join(parts))


def _text_of(path: Path) -> str:
    suffix = path.suffix
    if suffix == ".pdf":
        return " ".join(_pdf_pages(path.read_bytes()))
    if suffix == ".docx":
        return _docx_text(path)
    if suffix == ".xlsx":
        wb = load_workbook(path)
        cells = [str(c.value) for ws in wb for row in ws.iter_rows() for c in row if c.value]
        return _squash(" ".join(cells))
    if suffix == ".pptx":
        shapes = [s for sl in Presentation(str(path)).slides for s in sl.shapes]
        return _squash(" ".join(s.text_frame.text for s in shapes if s.has_text_frame))
    if suffix == ".eml":
        msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
        parts = [f"{msg['From']}"]
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                parts.append(part.get_content())
            elif part.get_content_type() == "application/pdf":
                parts += _pdf_pages(part.get_payload(decode=True))
        return _squash(" ".join(parts))
    return _squash(path.read_text(encoding="utf-8"))


def test_manifest_files_exist_and_hashes_match() -> None:
    for entry in [*DOCS, *INVALID]:
        path = CORPUS / entry["file"]
        assert path.is_file(), entry["file"]
        assert _sha(path) == entry["sha256"], entry["file"]
    listed = {e["file"] for e in [*DOCS, *INVALID]}
    on_disk = {
        p.relative_to(CORPUS).as_posix()
        for p in CORPUS.rglob("*")
        if p.is_file() and p.name != "manifest.yaml"
    }
    assert on_disk == listed


def test_manifest_ids_unique_and_tenants_known() -> None:
    ids = [d["id"] for d in DOCS]
    assert len(ids) == len(set(ids))
    assert ids == [f"A{n:02d}" for n in range(1, 14)] + ["B01", "B02"]
    tenants = MANIFEST["tenants"]
    assert set(tenants) == {"aurora", "boreal"}
    users = {t: {u["id"]: u for u in tenants[t]["users"]} for t in tenants}
    assert set(users["aurora"]) == {"ana", "rui", "carla", "eva", "vitor"}
    assert set(users["boreal"]) == {"bruno"}
    assert users["aurora"]["carla"]["role"] == "admin"
    for doc in DOCS:
        assert doc["tenant"] in tenants
        assert doc["classification"] in CLASSIFICATIONS
        assert doc["file"].startswith(doc["tenant"] + "/")


def test_every_restricted_or_confidential_doc_has_explicit_acl() -> None:
    sensitive = [d for d in DOCS if d["classification"] in {"restricted", "confidential"}]
    assert {d["id"] for d in sensitive} == {"A07", "A10", "A13"}
    for doc in sensitive:
        acl = doc["acl"]
        assert acl["all_members"] is False, doc["id"]
        assert acl["groups"] or acl["users"], doc["id"]
        groups = {g for u in MANIFEST["tenants"][doc["tenant"]]["users"] for g in u["groups"]}
        assert set(acl["groups"]) <= groups, doc["id"]


def test_corpus_total_size_under_3mb() -> None:
    total = sum(p.stat().st_size for p in CORPUS.rglob("*") if p.is_file())
    assert total < 3 * 1024 * 1024


@pytest.mark.parametrize("doc", [d for d in DOCS if d["id"] != "A10"], ids=lambda d: d["id"])
def test_facts_and_canaries_appear_in_documents(doc: dict[str, Any]) -> None:
    text = _text_of(CORPUS / doc["file"])
    for fact in doc["facts"]:
        assert _squash(fact) in text, (doc["id"], fact)
    for canary in doc["canaries"]:
        assert canary in text, (doc["id"], canary)


def test_a01_facts_are_on_the_documented_pages() -> None:
    pages = _pdf_pages((CORPUS / "aurora/manual_colaborador.pdf").read_bytes())
    assert len(pages) == 3
    assert "25 dias úteis de férias por ano" in pages[1]
    assert "horário de trabalho é das 9h00 às 18h00, com 1 hora de almoço" in pages[1]
    assert "teletrabalho até 2 dias por semana" in pages[2]
    assert "pedidos de férias com 30 dias de antecedência no portal RH" in pages[2]


def test_a03_notes_sheet_is_hidden_and_a09_has_three_hidden_runs() -> None:
    wb = load_workbook(CORPUS / "aurora/tabela_precos_2026.xlsx")
    assert wb["Notas"].sheet_state == "hidden"
    assert wb["Preços"].sheet_state == "visible"

    doc = Document(str(CORPUS / "aurora/sala_reunioes.docx"))
    runs = [r for p in doc.paragraphs for r in p.runs]
    assert any(r.font.color.rgb is not None and str(r.font.color.rgb) == "FFFFFF" for r in runs)
    assert any(r.font.hidden for r in runs)
    assert any(r.font.size is not None and r.font.size.pt == 1 for r in runs)


def test_a10_pdf_has_no_text_layer_and_has_an_image() -> None:
    reader = PdfReader(str(CORPUS / "aurora/contrato_limpeza_digitalizado.pdf"))
    assert all(not (p.extract_text() or "").strip() for p in reader.pages)
    assert sum(len(p.images) for p in reader.pages) >= 1


def test_a12_html_has_hidden_div_and_script() -> None:
    html = (CORPUS / "aurora/regulamento_interno.html").read_text(encoding="utf-8")
    assert '<div style="display:none">' in html
    assert "<script>" in html


def test_a06_eml_has_condicoes_attachment() -> None:
    msg = email.message_from_bytes(
        (CORPUS / "aurora/email_fornecedor.eml").read_bytes(), policy=policy.default
    )
    names = [p.get_filename() for p in msg.iter_attachments()]
    assert names == ["condicoes.pdf"]


def test_invalid_files_are_invalid_in_the_documented_way() -> None:
    inv = CORPUS / "invalid"
    assert PdfReader(str(inv / "encrypted.pdf")).is_encrypted
    with pytest.raises(Exception):  # noqa: B017 - qualquer erro de parsing serve
        PdfReader(str(inv / "truncated.pdf"), strict=True).pages[2].extract_text()
    assert not zipfile.is_zipfile(inv / "not_really.docx")
    with zipfile.ZipFile(inv / "zip_bomb.docx") as zf:
        info = max(zf.infolist(), key=lambda i: i.file_size)
        assert info.file_size >= 50 * 1024 * 1024
        assert info.file_size / max(info.compress_size, 1) > 100
    with zipfile.ZipFile(inv / "macro_template.docm") as zf:
        assert "word/vbaProject.bin" in zf.namelist()
    assert not zipfile.is_zipfile(inv / "random.bin")
    assert {e["file"] for e in INVALID} == {
        f"invalid/{n}"
        for n in (
            "encrypted.pdf",
            "truncated.pdf",
            "not_really.docx",
            "zip_bomb.docx",
            "macro_template.docm",
            "random.bin",
        )
    }
