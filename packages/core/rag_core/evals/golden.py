"""Modelo e carregador do golden set (``evals/golden/*.yaml``, C11)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml

from rag_core.types import AnswerKind, ChatMessage, Frozen

GoldenCategory = Literal[
    "answerable_single",
    "answerable_table",
    "multi_doc",
    "unanswerable",
    "acl_probe",
    "cross_tenant",
    "injection",
    "followup",
    "general_knowledge",
]

GOLDEN_DIR = Path(__file__).resolve().parents[4] / "evals" / "golden"


class GoldenItem(Frozen):
    """Uma pergunta com a resposta esperada, ligada aos factos do manifest."""

    id: str
    tenant: str
    user: str
    question: str
    category: GoldenCategory
    expected_doc_ids: tuple[str, ...] = ()
    expected_answer_contains: tuple[str, ...] = ()
    expected_kind: AnswerKind = "grounded"
    must_not_contain: tuple[str, ...] = ()
    history: tuple[ChatMessage, ...] | None = None


def load_golden(path: Path) -> list[GoldenItem]:
    """Lê e valida um ficheiro YAML do golden set."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path.name}: o golden set tem de ser uma lista de itens")
    return [GoldenItem.model_validate(entry) for entry in raw]


def load_all_golden(directory: Path = GOLDEN_DIR) -> list[GoldenItem]:
    """Lê todos os ``*.yaml`` do diretório, por ordem de nome."""
    return [item for path in sorted(directory.glob("*.yaml")) for item in load_golden(path)]
