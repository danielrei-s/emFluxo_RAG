#!/usr/bin/env python3
"""Gera o corpus sintético da C11 em ``fixtures/corpus`` e o ``manifest.yaml``.

Todas as empresas, pessoas, emails e números são fictícios. Os ficheiros gerados são commitados
com o SHA-256 no manifest. O gerador não é determinístico byte a byte (datas dentro dos ZIP):
o CI verifica os hashes do que está commitado e nunca regenera. Regenerar só de propósito.

Uso: ``python scripts/make_fixtures.py [--out fixtures/corpus]``
"""

from __future__ import annotations

import argparse
import hashlib
import io
import random
import zipfile
from pathlib import Path
from typing import Any

import yaml
from fixtures_docs import BUILDERS
from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "fixtures" / "corpus"

TENANTS: dict[str, Any] = {
    "aurora": {
        "name": "Aurora Distribuição, Lda.",
        "users": [
            {"id": "ana", "role": "member", "groups": ["comercial"]},
            {"id": "rui", "role": "member", "groups": ["rh"]},
            {"id": "carla", "role": "admin", "groups": ["direcao"]},
            {"id": "eva", "role": "editor", "groups": ["comercial"]},
            {"id": "vitor", "role": "viewer", "groups": []},
        ],
    },
    "boreal": {
        "name": "Boreal Consultoria, S.A.",
        "users": [{"id": "bruno", "role": "member", "groups": []}],
    },
}


# --------------------------------------------------------------------------- invalid


def _invalid(valid_pdf: bytes) -> dict[str, bytes]:
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(valid_pdf)))
    writer.encrypt("password")
    encrypted = io.BytesIO()
    writer.write(encrypted)

    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/zeros.bin", bytes(50 * 1024 * 1024))

    macro = io.BytesIO()
    with zipfile.ZipFile(macro, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<w:document/>")
        zf.writestr("word/vbaProject.bin", b"\xd0\xcf\x11\xe0 macro de teste")

    return {
        "encrypted.pdf": encrypted.getvalue(),
        "truncated.pdf": valid_pdf[: int(len(valid_pdf) * 0.7)],
        "not_really.docx": "Isto é apenas texto com extensão .docx.\n".encode(),
        "zip_bomb.docx": bomb.getvalue(),
        "macro_template.docm": macro.getvalue(),
        "random.bin": random.Random(20260101).randbytes(2048),  # noqa: S311 - dados de teste
    }


# ------------------------------------------------------------------------------ main


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def generate(out: Path) -> dict[str, Any]:
    """Escreve o corpus em ``out`` e devolve o manifest."""
    docs: list[dict[str, Any]] = []
    manual_pdf = b""
    for build in BUILDERS:
        spec = build()
        rel = f"{spec.tenant}/{spec.file}"
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(spec.content)
        if spec.id == "A01":
            manual_pdf = spec.content
        docs.append(
            {
                "id": spec.id,
                "file": rel,
                "tenant": spec.tenant,
                "classification": spec.classification,
                "acl": spec.acl,
                "facts": spec.facts,
                "canaries": spec.canaries,
                "sha256": _sha(spec.content),
            }
        )

    invalid: list[dict[str, Any]] = []
    for name, data in _invalid(manual_pdf).items():
        path = out / "invalid" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        invalid.append({"file": f"invalid/{name}", "sha256": _sha(data)})

    manifest = {"version": 1, "tenants": TENANTS, "documents": docs, "invalid": invalid}
    header = "# Gerado por scripts/make_fixtures.py. Não editar à mão.\n"
    body = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, width=100)
    (out / "manifest.yaml").write_text(header + body, encoding="utf-8", newline="\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    out = parser.parse_args().out
    manifest = generate(out)
    print(f"corpus: {len(manifest['documents'])} documentos + {len(manifest['invalid'])} inválidos")


if __name__ == "__main__":
    main()
