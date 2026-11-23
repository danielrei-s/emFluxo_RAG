"""Testes de F9-T02: o núcleo tem de ser agnóstico de sector e de serviços (INV-20)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import check_core_agnostic as cca  # noqa: E402


def test_inv20_core_agnostic_check_passes_on_repo() -> None:
    assert cca.check(cca.DEFAULT_CORE, cca.load_denylist(cca.DEFAULT_DENYLIST)) == []
    assert cca.main([]) == 0


def test_inv20_core_agnostic_check_flags_denylisted_term(tmp_path: Path) -> None:
    core = tmp_path / "rag_core"
    core.mkdir()
    (core / "limpo.py").write_text("x = 1\n", encoding="utf-8")
    (core / "sujo.py").write_text("# apenas para a Clínica Aurora\nx = 1\n", encoding="utf-8")
    (core / "imports.py").write_text(
        "import rag_gateway\nfrom services.gateway import app\nfrom modules.example import m\n",
        encoding="utf-8",
    )
    (core / "testing").mkdir()
    (core / "testing" / "dados.py").write_text("# aurora é permitido nos dados de teste\n")
    problems = cca.check(core, cca.load_denylist(cca.DEFAULT_DENYLIST))
    text = "\n".join(problems)
    assert "sujo.py: contém o termo proibido 'aurora'" in text
    assert "sujo.py: contém o termo proibido 'clínica'" in text
    assert text.count("imports.py") == 3
    assert "limpo.py" not in text and "dados.py" not in text
    assert cca.main(["--root", str(core)]) == 1
    (core / "sujo.py").unlink()
    (core / "imports.py").unlink()
    assert cca.main(["--root", str(core)]) == 0


def test_syntax_errors_are_reported(tmp_path: Path) -> None:
    core = tmp_path / "rag_core"
    core.mkdir()
    (core / "partido.py").write_text("def (:\n", encoding="utf-8")
    assert cca.check(core, []) == ["partido.py: sintaxe inválida"]
