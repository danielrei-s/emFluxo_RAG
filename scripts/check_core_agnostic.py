"""Garante que o núcleo é agnóstico (F9-T02; INV-20).

Analisa só ``packages/core/rag_core`` (não os testes): falha se importar de ``modules``,
``services`` ou ``apps``, ou se contiver termos da denylist (setores e slugs do corpus).

    uv run python scripts/check_core_agnostic.py [--root DIR] [--denylist FICHEIRO]
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORE = ROOT / "packages" / "core" / "rag_core"
DEFAULT_DENYLIST = Path(__file__).resolve().parent / "core_denylist.txt"
FORBIDDEN_IMPORTS = ("modules", "services", "apps", "rag_gateway", "rag_central", "rag_local")
# ficheiros do núcleo que existem para falar de dados de teste e não contam
EXEMPT_PREFIXES = ("testing/", "fakes/", "evals/")


def load_denylist(path: Path) -> list[str]:
    return [
        line.strip().lower()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def check(core: Path, denylist: list[str]) -> list[str]:
    problems: list[str] = []
    for path in sorted(core.rglob("*.py")):
        rel = path.relative_to(core).as_posix()
        if rel.startswith(EXEMPT_PREFIXES):
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            problems.append(f"{rel}: sintaxe inválida")
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for name in names:
                if name.split(".")[0] in FORBIDDEN_IMPORTS:
                    problems.append(f"{rel}:{node.lineno}: importa '{name}'")
        lowered = source.lower()
        for term in denylist:
            if re.search(rf"\b{re.escape(term)}\b", lowered):
                problems.append(f"{rel}: contém o termo proibido '{term}'")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--denylist", type=Path, default=DEFAULT_DENYLIST)
    args = parser.parse_args(argv)
    problems = check(args.root, load_denylist(args.denylist))
    for problem in problems:
        print(f"ERRO: {problem}", file=sys.stderr)
    print("núcleo agnóstico: OK" if not problems else f"{len(problems)} problema(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
