"""F10-T03: a lista de códigos de erro para o TypeScript acompanha o ``rag_core.errors``."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import export_error_codes as eec


def test_error_codes_json_is_up_to_date() -> None:
    assert eec.OUT.read_text(encoding="utf-8") == eec.render(), (
        "corre `uv run python scripts/export_error_codes.py` e faz commit do resultado"
    )
    assert "internal_error" in eec.error_codes() and "rate_limited" in eec.error_codes()
