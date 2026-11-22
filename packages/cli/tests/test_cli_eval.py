"""Testes de F5-T04: comando ``rag eval`` (ingestão no próprio processo para ser rápido)."""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Any

import pytest
import yaml
from rag_cli import main
from rag_core.evals.runner import run_eval
from rag_core.testing.indexed import inproc_runner
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[3]
runner = CliRunner()

GOLDEN = [
    {
        "id": "A-Q001", "tenant": "aurora", "user": "ana", "category": "answerable_single",
        "question": "Quantos dias de férias tenho por ano?",
        "expected_doc_ids": ["A01"], "must_not_contain": ["CANARIO"],
    },
]  # fmt: skip


@pytest.fixture(autouse=True)
def _fast_ingestion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "run_eval", partial(run_eval, runner=inproc_runner))


def _golden(tmp_path: Path, items: list[dict[str, Any]] | None = None) -> Path:
    path = tmp_path / "golden.yaml"
    path.write_text(yaml.safe_dump(items or GOLDEN, allow_unicode=True), encoding="utf-8")
    return path


def _args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "eval", "--fake-models", "--golden", str(_golden(tmp_path)),
        "--report", str(tmp_path / "out"), "--store-dir", str(tmp_path / "store"), *extra,
    ]  # fmt: skip


def test_eval_writes_report_and_baseline_and_passes_against_it(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    first = runner.invoke(main.app, _args(tmp_path, "--write-baseline", str(baseline)))
    assert first.exit_code == 0, first.output
    assert "recall_at_5: 1.000" in first.output and "leak_rate: 0.000" in first.output
    assert (tmp_path / "out" / "report.md").is_file()
    saved = json.loads(baseline.read_text(encoding="utf-8"))
    assert saved["config"] == "fake" and saved["metrics"]["n"] == 1

    again = runner.invoke(main.app, _args(tmp_path, "--baseline", str(baseline)))
    assert again.exit_code == 0, again.output


def test_eval_exits_1_on_regression_and_lists_it(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"metrics": {"recall_at_5": 1.0, "mrr": 1.0, "ndcg_at_5": 1.0}}),
        encoding="utf-8",
    )
    leaky = [{**GOLDEN[0], "must_not_contain": ["Manual do Colaborador"]}]
    golden = _golden(tmp_path, leaky)  # o eco do LLM falso contém a frase proibida
    result = runner.invoke(
        main.app,
        ["eval", "--fake-models", "--golden", str(golden), "--report", str(tmp_path / "out"),
         "--store-dir", str(tmp_path / "store"), "--baseline", str(baseline)],
    )  # fmt: skip
    assert result.exit_code == 1
    assert "regressão: leak_rate" in result.output
    assert "## Regressões" in (tmp_path / "out" / "report.md").read_text(encoding="utf-8")


def test_eval_input_errors(tmp_path: Path) -> None:
    def code(*args: str) -> int:
        return runner.invoke(main.app, list(args)).exit_code

    base = ["eval", "--fake-models", "--store-dir", str(tmp_path / "s")]
    assert code(*base, "--golden", str(tmp_path / "nao-existe")) == 2
    assert (
        code(*base, "--golden", str(_golden(tmp_path)), "--baseline", str(tmp_path / "x.json")) == 2
    )
    assert code(*base, "--manifest", str(tmp_path / "x.yaml")) == 2
    # sem --fake-models e sem models.yaml: erro claro
    assert (
        code("eval", "--golden", str(_golden(tmp_path)), "--models", str(tmp_path / "m.yaml")) == 2
    )


def test_committed_baseline_and_thresholds_are_valid() -> None:
    baseline = json.loads((ROOT / "evals" / "baseline.fake.json").read_text(encoding="utf-8"))
    assert baseline["config"] == "fake"
    assert baseline["metrics"]["leak_rate"] == 0.0
    assert baseline["metrics"]["n"] >= 55
    thresholds = yaml.safe_load((ROOT / "evals" / "thresholds.yaml").read_text(encoding="utf-8"))
    assert thresholds["live"]["floors"]["recall_at_5"] == 0.80
    assert thresholds["live"]["ceilings"]["leak_rate"] == 0.0
