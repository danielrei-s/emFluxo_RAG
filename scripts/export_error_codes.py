"""Gera ``packages/api-client/src/error-codes.json`` a partir de ``rag_core.errors`` (F10-T03).

    uv run python scripts/export_error_codes.py

O teste ``test_error_codes_json_is_up_to_date`` falha se o ficheiro ficar desatualizado.
"""

from __future__ import annotations

import json
from pathlib import Path

from rag_core import errors

OUT = Path(__file__).resolve().parents[1] / "packages" / "api-client" / "src" / "error-codes.json"


def error_codes() -> list[str]:
    codes = {
        obj.code
        for obj in vars(errors).values()
        if isinstance(obj, type) and issubclass(obj, errors.RagError) and obj is not errors.RagError
    }
    return sorted(codes | {errors.RagError.code})


def render() -> str:
    return json.dumps(error_codes(), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"escrito: {OUT}")


if __name__ == "__main__":
    main()
