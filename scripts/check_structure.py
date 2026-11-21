#!/usr/bin/env python3
"""Verifica que as pastas obrigatórias do monorepo (C3) existem.

Sai com código 1 se faltar alguma.
"""

from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_DIRS: tuple[str, ...] = (
    "packages/core/rag_core",
    "packages/core/tests/contract",
    "packages/cli",
    "packages/ui",
    "packages/web-common",
    "packages/api-client",
    "services/gateway",
    "services/central-api",
    "services/parser-sandbox",
    "apps/web",
    "apps/backoffice",
    "apps/local-engine",
    "apps/desktop",
    "modules",
    "evals",
    "fixtures/corpus",
    "infra/compose",
    "infra/db/migrations",
    "infra/cloudflare",
    "scripts",
    "docs/adr",
    "docs/plan",
    "docs/spec",
    "docs/product-web",
    "docs/product-local",
    "docs/runbooks",
    "docs/security",
    "docs/legal",
    ".github/workflows",
)


def missing_dirs(root: Path) -> list[str]:
    """Devolve as pastas obrigatórias que não existem sob ``root``."""
    return [d for d in REQUIRED_DIRS if not (root / d).is_dir()]


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    missing = missing_dirs(root)
    if missing:
        print("Pastas em falta:")
        for d in missing:
            print(f"  - {d}")
        return 1
    print("Estrutura OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
