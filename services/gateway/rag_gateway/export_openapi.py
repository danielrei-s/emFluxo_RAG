"""Gera ``services/gateway/openapi.json`` (usado por ``make openapi`` e pelo teste do snapshot)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rag_core.config import Settings

from rag_gateway.app import create_app

OPENAPI_PATH = Path(__file__).resolve().parents[1] / "openapi.json"


def build_openapi() -> dict[str, Any]:
    schema: dict[str, Any] = create_app(Settings.for_tests()).openapi()
    return schema


def render(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> None:
    OPENAPI_PATH.write_text(render(build_openapi()), encoding="utf-8", newline="\n")
    print(f"escrito: {OPENAPI_PATH}")


if __name__ == "__main__":
    main()
