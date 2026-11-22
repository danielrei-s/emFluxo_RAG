"""Testes de F5-T03: CLI ``rag`` (modelos falsos; a ingestão passa pelo sandbox real)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from rag_cli.main import app
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "fixtures" / "corpus"
MANIFEST = CORPUS / "manifest.yaml"
FILES = [
    "aurora/faq_rgpd.txt",
    "aurora/procedimento_faturacao.md",
    "aurora/rh_salarios_2026.xlsx",
    "aurora/manual_colaborador.pdf",
]
runner = CliRunner()


def _base(db: Path) -> list[str]:
    return ["--db", str(db), "--tenant", "aurora", "--manifest", str(MANIFEST), "--fake-models"]


@pytest.fixture(scope="module")
def corpus_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("cli")
    docs = base / "docs"
    docs.mkdir()
    for name in FILES:
        shutil.copy(CORPUS / name, docs / Path(name).name)
    (docs / "invalido.docx").write_text("isto não é um docx", encoding="utf-8")
    db = base / "index.db"
    result = runner.invoke(app, ["ingest", str(docs), *_base(db)])
    assert result.exit_code == 0, result.output
    return db


def test_ingest_prints_counts(corpus_db: Path, tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    shutil.copy(CORPUS / FILES[0], docs / "faq_rgpd.txt")
    db = tmp_path / "novo.db"
    first = runner.invoke(app, ["ingest", str(docs), *_base(db)])
    assert first.exit_code == 0
    assert "indexados: 1 | inalterados: 0 | falhados: 0" in first.output
    again = runner.invoke(app, ["ingest", str(docs / "faq_rgpd.txt"), *_base(db)])
    assert "indexados: 0 | inalterados: 1 | falhados: 0" in again.output

    (docs / "estragado.docx").write_text("não é um docx", encoding="utf-8")
    mixed = runner.invoke(app, ["ingest", str(docs), *_base(db)])
    assert "inalterados: 1" in mixed.output and "falhados: 1" in mixed.output
    assert "falhou: estragado.docx (corrupted_file)" in mixed.output


def test_ask_returns_answer_with_sources(corpus_db: Path) -> None:
    result = runner.invoke(
        app, ["ask", "Quantos dias de férias tenho por ano?", "--user", "ana", *_base(corpus_db)]
    )
    assert result.exit_code == 0, result.output
    assert "Fontes:" in result.output
    assert re.search(r"^\[1\] \S+\.(pdf|md|txt|xlsx)", result.output, re.MULTILINE)
    assert not re.search(r"[0-9a-f]{32}", result.output)  # sem chunk_id por omissão
    debug = runner.invoke(
        app,
        ["ask", "Quantos dias de férias tenho por ano?", "--user", "ana", "--debug-ids",
         *_base(corpus_db)],
    )  # fmt: skip
    assert re.search(r"chunk_ids: [0-9a-f]{32}", debug.output)


def test_ask_json_schema(corpus_db: Path) -> None:
    result = runner.invoke(
        app,
        ["ask", "Qual é o NIF da empresa?", "--user", "ana", "--json", *_base(corpus_db)],
    )
    assert result.exit_code == 0, result.output
    answer = json.loads(result.output)
    assert answer["kind"] in {"grounded", "general_knowledge", "not_found", "refused"}
    assert isinstance(answer["text"], str)
    assert isinstance(answer["citations"], list)
    for key in ("used_chunk_ids", "sent_excerpts", "warnings", "timings_ms"):
        assert key in answer
    assert set(answer["timings_ms"]) == {"retrieval", "llm", "total"}


def test_acl_via_manifest_user(corpus_db: Path) -> None:
    question = "Qual é o salário base de um Técnico Comercial?"
    for user in ("ana", "carla", "vitor"):
        denied = runner.invoke(app, ["ask", question, "--user", user, *_base(corpus_db)])
        assert denied.exit_code == 0
        assert "1350" not in denied.output and "CANARIO-RH" not in denied.output, user
        assert "rh_salarios" not in denied.output, user
    allowed = runner.invoke(app, ["ask", question, "--user", "rui", *_base(corpus_db)])
    assert "1350" in allowed.output
    assert "rh_salarios_2026.xlsx" in allowed.output


def test_exit_codes_on_errors(
    corpus_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(*args: str) -> int:
        return runner.invoke(app, list(args)).exit_code

    base = _base(corpus_db)
    assert run("ask", "   ", "--user", "ana", *base) == 2  # pergunta vazia
    assert run("ask", "x" * 5000, "--user", "ana", *base) == 2  # demasiado longa
    assert run("ask", "olá?", "--user", "fantasma", *base) == 2  # utilizador desconhecido
    assert run("ask", "olá?", "--tenant", "nada", "--db", str(corpus_db), "--fake-models") == 2
    assert run("ingest", str(tmp_path / "nao-existe"), *base) == 2
    empty = tmp_path / "vazia"
    empty.mkdir()
    unknown = ["--tenant", "nada", "--manifest", str(MANIFEST), "--fake-models"]
    assert run("ingest", str(empty), "--db", str(tmp_path / "x.db"), *unknown) == 0  # nada a fazer
    assert run("ask", "olá?", "--manifest", str(tmp_path / "falta.yaml"), "--fake-models") == 2
    assert run("eval") == 3  # ainda sem harness
    # sem --fake-models e sem models.yaml, falha com erro claro
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["ask", "olá?", "--db", str(tmp_path / "y.db")])
    assert result.exit_code == 2
    assert "models_file_missing" in result.output


def test_models_check(tmp_path: Path) -> None:
    ok = runner.invoke(app, ["models", "check", "--models", str(ROOT / "models.example.yaml")])
    assert ok.exit_code == 0
    assert "ok: rag-default (llm, openai_compat, Apache-2.0)" in ok.output
    bad = tmp_path / "models.yaml"
    bad.write_text(
        "models:\n  m:\n    kind: llm\n    backend: x\n    model: m\n    license: CC-BY-NC-4.0\n",
        encoding="utf-8",
    )
    assert runner.invoke(app, ["models", "check", "--models", str(bad)]).exit_code == 2
    broken = tmp_path / "broken.yaml"
    broken.write_text("models:\n  m:\n    kind: desconhecido\n", encoding="utf-8")
    assert runner.invoke(app, ["models", "check", "--models", str(broken)]).exit_code == 2
    assert (
        runner.invoke(app, ["models", "check", "--models", str(tmp_path / "x.yaml")]).exit_code == 2
    )


def test_models_check_verifies_hashes_with_cache_dir(tmp_path: Path) -> None:
    from rag_core.ids import sha256_hex

    cache = tmp_path / "cache"
    cache.mkdir()
    registry = tmp_path / "models.yaml"
    registry.write_text(
        "models:\n  emb:\n    kind: embedding\n    backend: fastembed\n    model: m\n"
        f"    license: MIT\n    dim: 4\n    revision: abc\n    files:\n"
        f"      - {{name: model.onnx, sha256: {sha256_hex(b'pesos')}}}\n",
        encoding="utf-8",
    )
    args = ["models", "check", "--models", str(registry), "--cache-dir", str(cache)]
    assert runner.invoke(app, args).exit_code == 2  # ficheiro em falta
    (cache / "model.onnx").write_bytes(b"adulterado")
    assert runner.invoke(app, args).exit_code == 2  # hash errado
    (cache / "model.onnx").write_bytes(b"pesos")
    assert runner.invoke(app, args).exit_code == 0


def test_help_works_as_a_command_and_as_a_module() -> None:
    assert "ingest" in runner.invoke(app, ["--help"]).output
    done = subprocess.run(
        [sys.executable, "-m", "rag_cli", "--help"], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0 and "ask" in done.stdout


def test_real_models_wiring_resolves_the_base_url(tmp_path: Path) -> None:
    from rag_cli.wiring import build_runtime
    from rag_core.errors import ValidationFailed

    models = tmp_path / "models.yaml"
    models.write_text((ROOT / "models.example.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ValidationFailed) as exc:  # RAG_OLLAMA_URL não definido
        build_runtime(tmp_path / "a.db", fake_models=False, models_file=models)
    assert exc.value.subcode == "model_base_url_missing"

    onnx = tmp_path / "onnx.yaml"
    onnx.write_text(
        "models:\n  rag-default:\n    kind: llm\n    backend: fastembed\n    model: m\n"
        "    license: MIT\n  rag-embed:\n    kind: embedding\n    backend: fastembed\n"
        "    model: m\n    license: MIT\n    dim: 4\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationFailed) as unsupported:
        build_runtime(tmp_path / "b.db", fake_models=False, models_file=onnx)
    assert unsupported.value.subcode == "unsupported_backend"


def test_models_file_without_models_section_is_a_clear_error(tmp_path: Path) -> None:
    only_ocr = tmp_path / "models.yaml"
    only_ocr.write_text("ocr_models:\n  rapidocr: {}\n", encoding="utf-8")
    result = runner.invoke(app, ["models", "check", "--models", str(only_ocr)])
    assert result.exit_code == 2
    assert "models_section_missing" in result.output
    db = str(tmp_path / "z.db")
    asked = runner.invoke(app, ["ask", "olá?", "--db", db, "--models", str(only_ocr)])
    assert asked.exit_code == 2 and "models_section_missing" in asked.output
