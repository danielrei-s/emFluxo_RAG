"""Testes de F3-T01: deteção de tipo e validação de ficheiros (sem chamar parsers)."""

from __future__ import annotations

import contextlib
import io
import struct
import zipfile

import pytest
from hypothesis import given
from hypothesis import strategies as st
from PIL import Image
from rag_core.errors import (
    CorruptedFile,
    EncryptedFile,
    FileTooLarge,
    RagError,
    UnsupportedType,
    ValidationFailed,
)
from rag_core.ingestion import detect_type, sniff, validate_file
from rag_core.interfaces import ParseLimits
from rag_core.testing import corpus
from rag_core.types import DetectedType

INVALID = corpus.CORPUS_DIR / "invalid"
LIMITS = ParseLimits()
FREE, ENDCHAIN, FATSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _ole(stream_name: str) -> bytes:
    """Ficheiro OLE2 (CFB v3) mínimo com um único stream de 4096 bytes."""
    header = OLE_MAGIC + bytes(16)
    header += struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + bytes(6)
    header += struct.pack("<IIIIIIIII", 0, 1, 1, 0, 4096, ENDCHAIN, 0, ENDCHAIN, 0)
    header += struct.pack("<I", 0) + struct.pack("<I", FREE) * 108
    fat = [FATSECT, ENDCHAIN, *range(3, 10), ENDCHAIN] + [FREE] * 118
    fat_sector = struct.pack("<128I", *fat)

    def entry(name: str, kind: int, child: int, start: int, size: int) -> bytes:
        raw = name.encode("utf-16-le")
        head = raw.ljust(64, b"\0") + struct.pack("<HBB", len(raw) + 2 if raw else 0, kind, 1)
        head += struct.pack("<III", FREE, FREE, child) + bytes(16) + bytes(4) + bytes(16)
        return head + struct.pack("<IQ", start, size)

    empty = entry("", 0, FREE, 0, 0)
    directory = entry("Root Entry", 5, 1, ENDCHAIN, 0) + entry(stream_name, 2, FREE, 2, 4096)
    directory += empty + empty
    return header + fat_sector + directory + bytes(4096)


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _image(fmt: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, format=fmt)
    return buf.getvalue()


# ----------------------------------------------------------------------- deteção


@pytest.mark.parametrize(
    ("doc_id", "expected"),
    [
        ("A01", DetectedType.PDF),
        ("A10", DetectedType.PDF),
        ("A02", DetectedType.DOCX),
        ("A03", DetectedType.XLSX),
        ("A04", DetectedType.PPTX),
        ("A05", DetectedType.MD),
        ("A06", DetectedType.EML),
        ("A11", DetectedType.TXT),
        ("A12", DetectedType.HTML),
        ("A13", DetectedType.CSV),
    ],
)
def test_detects_corpus_types(doc_id: str, expected: DetectedType) -> None:
    filename = corpus.source_file_for(doc_id).filename
    assert detect_type(corpus.read_bytes(doc_id), filename) == expected


def test_detects_images() -> None:
    assert detect_type(_image("PNG"), "x.png") == DetectedType.PNG
    assert detect_type(_image("JPEG"), "x.jpg") == DetectedType.JPEG
    assert detect_type(_image("TIFF"), "x.tif") == DetectedType.TIFF
    assert detect_type(b"MM\x00*" + bytes(8), "x.tif") == DetectedType.TIFF


def test_detects_by_content_when_extension_is_misleading() -> None:
    assert detect_type(corpus.read_bytes("A01"), "relatorio.txt") == DetectedType.PDF
    assert detect_type(b"  <!DOCTYPE html><p>oi</p>", "pagina.txt") == DetectedType.HTML
    assert detect_type(b"<html><body>oi</body></html>", "x") == DetectedType.HTML
    eml = b"Received: from a\r\nFrom: a@b.example\r\n\r\ncorpo"
    assert detect_type(eml, "mensagem.txt") == DetectedType.EML
    assert detect_type("café".encode("cp1252"), "n.txt") == DetectedType.TXT
    assert detect_type(b"ol\xc3\xa1", "n.bin") == DetectedType.TXT


def test_detects_ole_msg_and_encrypted_office() -> None:
    assert detect_type(_ole("__substg1.0_0037001F"), "m.msg") == DetectedType.MSG
    with pytest.raises(EncryptedFile):
        detect_type(_ole("EncryptionInfo"), "x.docx")
    with pytest.raises(UnsupportedType):
        detect_type(_ole("WordDocument"), "antigo.doc")
    with pytest.raises(CorruptedFile):
        detect_type(OLE_MAGIC + bytes(40), "x.doc")


def test_unsupported_types() -> None:
    with pytest.raises(UnsupportedType):
        detect_type(_zip({"a.txt": b"x"}), "a.zip")
    with pytest.raises(UnsupportedType):
        detect_type((INVALID / "random.bin").read_bytes(), "random.bin")
    with pytest.raises(UnsupportedType):
        detect_type(b"abc\x81", "x.txt")  # nem UTF-8 nem cp1252


# ---------------------------------------------------------------------- rejeição


def test_encrypted_pdf_rejected() -> None:
    with pytest.raises(EncryptedFile):
        sniff((INVALID / "encrypted.pdf").read_bytes(), "encrypted.pdf", LIMITS)


def test_truncated_pdf_rejected() -> None:
    with pytest.raises(CorruptedFile):
        sniff((INVALID / "truncated.pdf").read_bytes(), "truncated.pdf", LIMITS)


def test_zip_bomb_rejected() -> None:
    with pytest.raises(ValidationFailed) as exc:
        sniff((INVALID / "zip_bomb.docx").read_bytes(), "zip_bomb.docx", LIMITS)
    assert exc.value.subcode == "zip_bomb"
    small = ParseLimits(max_unzipped_bytes=10)
    with pytest.raises(ValidationFailed) as exc2:
        sniff(corpus.read_bytes("A02"), "politica_despesas.docx", small)
    assert exc2.value.subcode == "zip_bomb"


def test_text_renamed_as_docx_rejected() -> None:
    with pytest.raises(CorruptedFile):
        sniff((INVALID / "not_really.docx").read_bytes(), "not_really.docx", LIMITS)
    with pytest.raises(CorruptedFile):
        validate_file(b"texto", "x.xlsx", DetectedType.TXT, LIMITS)


def test_zip_path_traversal_rejected() -> None:
    for name in ("../evil.xml", "word/../../evil.xml", "/etc/passwd", "C:/x.xml", "..\\x.xml"):
        data = _zip({"word/document.xml": b"<w/>", name: b"x"})
        with pytest.raises(ValidationFailed) as exc:
            sniff(data, "x.docx", LIMITS)
        assert exc.value.subcode == "zip_path_traversal", name


def test_corrupt_zip_rejected() -> None:
    with pytest.raises(CorruptedFile):
        sniff(b"PK\x03\x04" + b"lixo" * 20, "x.docx", LIMITS)


def test_oversize_and_empty_rejected() -> None:
    with pytest.raises(FileTooLarge):
        sniff(corpus.read_bytes("A01"), "manual.pdf", ParseLimits(max_bytes=100))
    with pytest.raises(CorruptedFile):
        sniff(b"", "vazio.txt", LIMITS)


def test_macro_flagged() -> None:
    data = (INVALID / "macro_template.docm").read_bytes()
    detected, warnings = sniff(data, "macro_template.docm", LIMITS)
    assert detected == DetectedType.DOCX
    assert warnings == ["has_macros"]


def test_sniff_returns_type_and_no_warnings_for_clean_corpus() -> None:
    for doc_id in ("A01", "A02", "A03", "A04", "A06", "A12"):
        name = corpus.source_file_for(doc_id).filename
        detected, warnings = sniff(corpus.read_bytes(doc_id), name, LIMITS)
        assert isinstance(detected, DetectedType)
        assert warnings == []


@given(data=st.binary(max_size=600), name=st.sampled_from(["a.docx", "a.pdf", "a.txt", "a"]))
def test_random_bytes_never_crash(data: bytes, name: str) -> None:
    try:
        detected, warnings = sniff(data, name, LIMITS)
    except RagError:
        return
    assert isinstance(detected, DetectedType)
    assert isinstance(warnings, list)


@given(
    tail=st.binary(max_size=300),
    head=st.sampled_from([b"PK\x03\x04", b"%PDF-", OLE_MAGIC]),
)
def test_random_bytes_with_valid_magic_never_crash(tail: bytes, head: bytes) -> None:
    with contextlib.suppress(RagError):
        sniff(head + tail, "x.docx", LIMITS)


def test_validate_file_enforces_size_on_its_own() -> None:
    with pytest.raises(FileTooLarge):
        validate_file(b"x" * 10, "a.txt", DetectedType.TXT, ParseLimits(max_bytes=5))
