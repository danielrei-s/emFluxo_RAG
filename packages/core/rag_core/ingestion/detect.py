"""Deteção do tipo real de um ficheiro e validação prévia ao parsing (F3-T01).

Só lê cabeçalhos e o índice do ZIP: nenhum parser é chamado aqui.
"""

from __future__ import annotations

import io
import re
import struct
import zipfile
from pathlib import PurePath

from rag_core.errors import (
    CorruptedFile,
    EncryptedFile,
    FileTooLarge,
    UnsupportedType,
    ValidationFailed,
)
from rag_core.interfaces import ParseLimits
from rag_core.types import DetectedType

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
MAX_ZIP_RATIO = 100
OFFICE_EXTENSIONS = frozenset(
    {".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm", ".doc", ".xls", ".ppt"}
)
_ZIP_ERRORS = (zipfile.BadZipFile, ValueError, OverflowError, NotImplementedError, struct.error)
_ZIP_MARKERS = {
    "word/document.xml": DetectedType.DOCX,
    "xl/workbook.xml": DetectedType.XLSX,
    "ppt/presentation.xml": DetectedType.PPTX,
}
_EML_HEADER = re.compile(rb"^(From|Received|MIME-Version):", re.IGNORECASE | re.MULTILINE)
_TEXT_BY_EXTENSION = {
    ".md": DetectedType.MD,
    ".markdown": DetectedType.MD,
    ".csv": DetectedType.CSV,
    ".html": DetectedType.HTML,
    ".htm": DetectedType.HTML,
    ".eml": DetectedType.EML,
}


def _extension(filename: str) -> str:
    return PurePath(filename).suffix.lower()


def _zip_infos(data: bytes) -> list[zipfile.ZipInfo]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return zf.infolist()
    except _ZIP_ERRORS as exc:
        raise CorruptedFile("zip_unreadable") from exc


def _is_unsafe_path(name: str) -> bool:
    path = name.replace("\\", "/")
    return path.startswith("/") or bool(re.match(r"^[A-Za-z]:", path)) or ".." in path.split("/")


def _check_zip(data: bytes, limits: ParseLimits) -> list[str]:
    """Rejeita bombas e path traversal; devolve ``["has_macros"]`` se houver macros VBA."""
    infos = _zip_infos(data)
    total = sum(i.file_size for i in infos)
    if total > limits.max_unzipped_bytes or total / max(len(data), 1) > MAX_ZIP_RATIO:
        raise ValidationFailed(subcode="zip_bomb")
    if any(_is_unsafe_path(i.filename) for i in infos):
        raise ValidationFailed(subcode="zip_path_traversal")
    if any(i.filename.endswith("vbaProject.bin") for i in infos):
        return ["has_macros"]
    return []


def _ole_stream_names(data: bytes) -> list[str]:
    import olefile  # extra "lite"

    try:
        with olefile.OleFileIO(io.BytesIO(data)) as ole:
            return ["/".join(entry) for entry in ole.listdir(streams=True, storages=False)]
    except Exception as exc:  # olefile levanta tipos variados em ficheiros corrompidos
        raise CorruptedFile("ole_unreadable") from exc


def _detect_ole(data: bytes) -> DetectedType:
    names = _ole_stream_names(data)
    parts = [part for name in names for part in name.split("/")]
    if "EncryptionInfo" in parts:
        raise EncryptedFile("ooxml_encrypted")
    if any(part.startswith("__substg1.0_") for part in parts):
        return DetectedType.MSG
    raise UnsupportedType("legacy_office")


def _detect_zip(data: bytes) -> DetectedType:
    names = {i.filename for i in _zip_infos(data)}
    for marker, detected in _ZIP_MARKERS.items():
        if marker in names:
            return detected
    raise UnsupportedType("zip_unknown_content")


def _decodes_as_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    for encoding in ("utf-8", "cp1252"):
        try:
            data.decode(encoding)
        except UnicodeDecodeError:
            continue
        return True
    return False


def _detect_text(data: bytes, filename: str) -> DetectedType:
    if not _decodes_as_text(data):
        raise UnsupportedType("binary")
    by_extension = _TEXT_BY_EXTENSION.get(_extension(filename))
    if by_extension is not None:
        return by_extension
    start = data[:2048].lstrip().lower()
    if start.startswith((b"<!doctype html", b"<html")):
        return DetectedType.HTML
    if _EML_HEADER.search(b"\n".join(data[:4096].splitlines()[:20])):
        return DetectedType.EML
    return DetectedType.TXT


def detect_type(data: bytes, filename: str) -> DetectedType:
    """Identifica o tipo real pelo conteúdo (magic bytes), não pela extensão."""
    if data.startswith(b"%PDF-"):
        return DetectedType.PDF
    if data.startswith(b"PK\x03\x04"):
        return _detect_zip(data)
    if data.startswith(OLE_MAGIC):
        return _detect_ole(data)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return DetectedType.PNG
    if data.startswith(b"\xff\xd8\xff"):
        return DetectedType.JPEG
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return DetectedType.TIFF
    return _detect_text(data, filename)


def validate_file(
    data: bytes, filename: str, detected: DetectedType, limits: ParseLimits
) -> list[str]:
    """Valida o ficheiro antes do parsing. Devolve avisos (ex.: ``has_macros``)."""
    if len(data) > limits.max_bytes:
        raise FileTooLarge()
    if not data:
        raise CorruptedFile("empty")
    is_container = data.startswith((b"PK\x03\x04", OLE_MAGIC))
    if _extension(filename) in OFFICE_EXTENSIONS and not is_container:
        raise CorruptedFile("office_extension_not_container")
    warnings: list[str] = []
    if data.startswith(b"PK\x03\x04"):
        warnings = _check_zip(data, limits)
    if detected == DetectedType.PDF:
        if b"/Encrypt" in data[-4096:]:
            raise EncryptedFile("pdf_encrypted")
        if b"%%EOF" not in data[-2048:]:
            raise CorruptedFile("pdf_truncated")
    return warnings


def sniff(
    data: bytes, filename: str, limits: ParseLimits | None = None
) -> tuple[DetectedType, list[str]]:
    """Valida e deteta o tipo. Devolve ``(tipo, avisos)`` ou levanta um ``RagError``."""
    limits = limits or ParseLimits()
    if len(data) > limits.max_bytes:
        raise FileTooLarge()
    if data.startswith(b"PK\x03\x04"):
        _check_zip(data, limits)  # antes de detetar: uma bomba tem de falhar como bomba
    detected = detect_type(data, filename)
    return detected, validate_file(data, filename, detected, limits)
