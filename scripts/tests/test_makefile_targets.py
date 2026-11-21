"""Testes de F0-T04: o Makefile expõe os alvos padrão da C10."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")

REQUIRED_TARGETS = (
    "help",
    "setup",
    "setup-full",
    "lint",
    "test",
    "test-integration",
    "test-e2e",
    "eval",
    "eval-live",
    "security",
    "licenses",
    "openapi",
    "fixtures",
    "migrate",
    "up",
    "down",
    "hooks",
)


def _targets() -> dict[str, str]:
    """Devolve ``alvo -> descrição`` (texto após ``##``) para cada alvo declarado."""
    found: dict[str, str] = {}
    for match in re.finditer(r"^([a-z][a-z0-9-]*):[^=\n]*?(?:## (.*))?$", MAKEFILE, re.M):
        found[match.group(1)] = match.group(2) or ""
    return found


def test_required_targets_present() -> None:
    assert [t for t in REQUIRED_TARGETS if t not in _targets()] == []


def test_every_required_target_has_help_description() -> None:
    targets = _targets()
    assert [t for t in REQUIRED_TARGETS if not targets[t].strip()] == []


def test_makefile_uses_strict_shell_flags() -> None:
    assert ".SHELLFLAGS := -eu -o pipefail -c" in MAKEFILE


def test_unimplemented_targets_name_their_task() -> None:
    stubs = re.findall(r"ainda não implementado \((F\d+-T\d+)\)", MAKEFILE)
    assert stubs, "nenhum alvo-stub encontrado"
