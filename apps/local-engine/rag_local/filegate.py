"""FileGate: a única porta de acesso a ficheiros do utilizador (F11-T04; INV-10).

Todo o código do motor que lê ficheiros do utilizador passa por aqui; os parsers recebem bytes.
Listar só lê metadados (consentimento de nível 1); ler exige um documento ``approved`` ou
``indexed``, dentro da raiz autorizada e não excluído.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from rag_core.errors import ConsentError, FileTooLarge, ValidationFailed

from rag_local.consent import State
from rag_local.exclusions import exclusion_reason
from rag_local.repo import LocalRepo

_WINDOWS_SYSTEM = ("c:\\windows", "c:\\program files", "c:\\program files (x86)", "c:\\programdata")
_POSIX_SYSTEM = (
    "/system",
    "/library",
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/var",
    "/proc",
    "/dev",
    "/sys",
)
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)


@dataclass(frozen=True)
class FileMeta:
    rel_path: str
    name: str
    size: int
    mtime: float
    ext: str


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _inside(root: str, real: str) -> bool:
    try:
        return os.path.commonpath([_norm(root), _norm(real)]) == _norm(root)
    except ValueError:  # unidades diferentes no Windows
        return False


class FileGate:
    def __init__(self, repo: LocalRepo) -> None:
        self._repo = repo

    # ------------------------------------------------------------------ raízes
    def register_root(self, path: str, *, allow_home: bool = False) -> str:
        """Caminho canónico se for uma pasta aceitável; ``ValidationFailed`` caso contrário."""
        if path.startswith(("\\\\?\\", "\\\\.\\")):
            raise ValidationFailed(subcode="device_path")
        real = os.path.realpath(path)
        if not os.path.isdir(real):
            raise ValidationFailed(subcode="not_a_directory")
        if os.path.dirname(real) == real:
            raise ValidationFailed(subcode="filesystem_root")
        lowered = _norm(real)
        if not allow_home and lowered == _norm(os.path.realpath(str(Path.home()))):
            raise ValidationFailed(subcode="home_folder")
        system = _WINDOWS_SYSTEM if sys.platform == "win32" else _POSIX_SYSTEM
        for prefix in system:
            base = _norm(prefix)
            if lowered == base or lowered.startswith(base + os.sep):
                raise ValidationFailed(subcode="system_folder")
        return real

    # --------------------------------------------------------------- caminhos
    def resolve(self, workspace_id: str, rel_path: str) -> Path:
        root = self._root(workspace_id)
        if not rel_path or os.path.isabs(rel_path) or rel_path.startswith(("/", "\\")):
            raise ValidationFailed(subcode="invalid_path")
        parts = [p for p in re.split(r"[\\/]", rel_path) if p not in ("", ".")]
        if ".." in parts:
            raise ValidationFailed(subcode="path_traversal")
        if ":" in rel_path:  # Alternate Data Streams e letras de unidade
            raise ValidationFailed(subcode="invalid_path")
        if any(_RESERVED.match(part.split(".")[0]) for part in parts):
            raise ValidationFailed(subcode="reserved_name")
        real = os.path.realpath(os.path.join(root, *parts))
        if not _inside(root, real):  # symlinks e junctions que saem da raiz
            raise ValidationFailed(subcode="path_escape")
        return Path(real)

    def _root(self, workspace_id: str) -> str:
        for workspace in self._repo.workspaces():
            if workspace["id"] == workspace_id:
                return str(os.path.realpath(workspace["root_path"]))
        raise ValidationFailed(subcode="unknown_workspace")

    # ------------------------------------------------------------- listagem
    def list_files(self, workspace_id: str) -> list[FileMeta]:
        """Metadados dos ficheiros não excluídos; não abre nem lê nenhum ficheiro."""
        root = self._root(workspace_id)
        found: list[FileMeta] = []
        stack = [(root, "")]
        while stack:
            directory, prefix = stack.pop()
            with os.scandir(directory) as entries:
                for entry in sorted(entries, key=lambda e: e.name):
                    rel = f"{prefix}{entry.name}"
                    if entry.is_symlink() or entry.is_junction():
                        continue  # nunca se segue um atalho
                    if entry.is_dir(follow_symlinks=False):
                        if exclusion_reason(rel + "/x") is None:
                            stack.append((entry.path, rel + "/"))
                        continue
                    if not entry.is_file(follow_symlinks=False) or exclusion_reason(rel):
                        continue
                    info = entry.stat(follow_symlinks=False)
                    found.append(
                        FileMeta(
                            rel,
                            entry.name,
                            info.st_size,
                            info.st_mtime,
                            os.path.splitext(entry.name)[1].lower(),
                        )
                    )
        return sorted(found, key=lambda f: f.rel_path)

    # -------------------------------------------------------------- leitura
    def read_bytes(self, doc_id: str, max_bytes: int) -> tuple[bytes, bool]:
        """Bytes do documento aprovado e se mudou desde a listagem (``True`` pede re-hash)."""
        doc = self._repo.document(doc_id)
        if State(doc["state"]) not in (State.APPROVED, State.INDEXED):
            raise ConsentError("not_approved")
        if exclusion_reason(doc["rel_path"]) is not None:
            raise ConsentError("excluded")
        path = self.resolve(doc["workspace_id"], doc["rel_path"])
        with open(path, "rb") as handle:
            info = os.fstat(handle.fileno())
            if info.st_size > max_bytes:
                raise FileTooLarge()
            data = handle.read(max_bytes + 1)
        changed = info.st_size != doc["size"] or abs(info.st_mtime - doc["mtime"]) > 1e-6
        return data, changed
