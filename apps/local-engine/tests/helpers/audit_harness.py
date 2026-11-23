"""Corre listar + aprovar + ler uma pasta com um audit hook que regista os ``open`` (INV-10).

Uso: ``python audit_harness.py <raiz do workspace>``. Imprime uma linha JSON com os caminhos
abertos em cada fase (``list`` e ``read``), para o teste os comparar com as pastas permitidas.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys

opened: dict[str, list[str]] = {"setup": [], "list": [], "read": []}
phase = "setup"


def hook(event: str, args: tuple[object, ...]) -> None:
    if event == "open" and args and isinstance(args[0], str | bytes | os.PathLike):
        path = os.fsdecode(args[0])
        if path and not path.isdigit():
            opened[phase].append(os.path.realpath(path))


sys.addaudithook(hook)

from rag_local.consent import Action  # noqa: E402
from rag_local.filegate import FileGate  # noqa: E402
from rag_local.repo import LocalRepo  # noqa: E402


def main(root: str) -> None:
    global phase
    repo = LocalRepo(sqlite3.connect(":memory:"))
    gate = FileGate(repo)
    canonical = gate.register_root(root)
    workspace = repo.add_workspace(canonical, "Teste")
    phase = "list"
    files = gate.list_files(workspace)
    phase = "read"
    for meta in files:
        doc = repo.propose(workspace, meta.rel_path, meta.size, meta.mtime, meta.ext)
        if doc is not None:
            repo.apply(doc, Action.APPROVE)
            gate.read_bytes(doc, 10_000_000)
    phase = "done"
    print(json.dumps({"opened": opened, "listed": [f.rel_path for f in files]}))


if __name__ == "__main__":
    main(sys.argv[1])
