"""Ficheiros que nunca se indexam (F11-T03): segredos, chaves, ficheiros do sistema e BDs."""

from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath

# (padrão, motivo). Padrões de nome comparam só o nome; "dir/" compara qualquer pasta do caminho.
NAME_PATTERNS: tuple[tuple[str, str], ...] = (
    (".env", "ficheiro de ambiente com segredos"),
    (".env.*", "ficheiro de ambiente com segredos"),
    ("*.pem", "chave ou certificado"),
    ("*.key", "chave privada"),
    ("*.p12", "chave ou certificado"),
    ("*.pfx", "chave ou certificado"),
    ("id_rsa*", "chave SSH"),
    ("id_ed25519*", "chave SSH"),
    ("*.kdbx", "cofre de palavras-passe"),
    ("*.keychain*", "cofre de palavras-passe"),
    ("wallet.dat", "carteira de criptomoeda"),
    ("*.wallet", "carteira de criptomoeda"),
    ("*.sqlite", "base de dados"),
    ("*.db", "base de dados"),
    ("*.lnk", "atalho do sistema"),
    ("desktop.ini", "metadados do sistema"),
    ("thumbs.db", "metadados do sistema"),
    (".ds_store", "metadados do sistema"),
)
DIR_NAMES: tuple[tuple[str, str], ...] = (
    (".git", "repositório de código"),
    (".ssh", "chaves SSH"),
    ("node_modules", "dependências de código"),
    ("__pycache__", "ficheiros temporários de código"),
    (".venv", "ambiente virtual"),
)


def exclusion_reason(rel_path: str) -> str | None:
    """Motivo da exclusão (sem distinguir maiúsculas) ou ``None`` se pode ser proposto."""
    normalized = rel_path.replace("\\", "/")
    parts = [p for p in PurePosixPath(normalized).parts if p not in ("", ".")]
    if not parts:
        return None
    lowered_dirs = [p.lower() for p in parts[:-1]]
    for name, reason in DIR_NAMES:
        if name in lowered_dirs:
            return reason
    filename = parts[-1].lower()
    for pattern, reason in NAME_PATTERNS:
        if fnmatch.fnmatchcase(filename, pattern):
            return reason
    return None


def is_excluded(rel_path: str) -> bool:
    return exclusion_reason(rel_path) is not None


__all__ = ["exclusion_reason", "is_excluded"]
