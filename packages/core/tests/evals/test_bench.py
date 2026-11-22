"""Testes de F5-T05: o script de benchmark (ensaio com fakes; sem modelos reais)."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest
import yaml
from rag_core.testing.indexed import inproc_runner

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "evals" / "bench" / "run_bench.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_bench", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # os dataclasses precisam do módulo registado
    spec.loader.exec_module(module)
    return module


bench = _load()
GOLDEN = [
    {
        "id": "A-Q001", "tenant": "aurora", "user": "ana", "category": "answerable_single",
        "question": "Quantos dias de férias tenho por ano?", "expected_doc_ids": ["A01"],
    }
]  # fmt: skip


def test_bench_script_dry_run(tmp_path: Path) -> None:
    golden = tmp_path / "golden.yaml"
    golden.write_text(yaml.safe_dump(GOLDEN, allow_unicode=True), encoding="utf-8")
    combos = bench.parse_combos(["fake-a"], ["none"], ["fake-llm"])
    rows = bench.run_bench(
        combos, golden=[golden], store_dir=tmp_path / "s", manifest=bench.DEFAULT_MANIFEST,
        models_file=None, dry_run=True, runner=inproc_runner,
    )  # fmt: skip
    markdown = bench.render_markdown(rows, date(2026, 12, 1), dry_run=True)
    lines = markdown.splitlines()
    assert lines[0] == "# Benchmark de modelos (2026-12-01) — ensaio com fakes"
    header = next(line for line in lines if line.startswith("| Combinação"))
    for column in (
        "recall@5",
        "mrr",
        "fugas",
        "fallback",
        "emb/s",
        "TTFT p50",
        "p95",
        "RSS",
        "VRAM",
    ):
        assert column in header
    row = next(line for line in lines if line.startswith("| fake-a / sem reranker / fake-llm"))
    assert row.count("|") == header.count("|")
    assert "1.000" in row  # recall@5 do único item
    assert "docs/adr/0009-modelos-v1.md" in markdown
    assert rows[0].embeddings_per_s > 0 and rows[0].rss_mb > 0


def test_main_writes_the_report_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = bench.run_eval
    monkeypatch.setattr(
        bench, "run_eval", lambda *a, **k: original(*a, **{**k, "runner": inproc_runner})
    )
    golden = tmp_path / "golden.yaml"
    golden.write_text(yaml.safe_dump(GOLDEN, allow_unicode=True), encoding="utf-8")
    out = tmp_path / "relatorios" / "r.md"
    code = bench.main(
        [
            "--dry-run",
            "--golden",
            str(golden),
            "--store-dir",
            str(tmp_path / "s"),
            "--out",
            str(out),
        ]
    )
    assert code == 0 and out.is_file()
    assert "Benchmark de modelos" in capsys.readouterr().out


def test_combos_percentiles_and_gpu_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    combos = bench.parse_combos(["e1", "e2"], ["none", "r1"], ["m1"])
    assert [c.label for c in combos] == [
        "e1 / sem reranker / m1", "e1 / r1 / m1", "e2 / sem reranker / m1", "e2 / r1 / m1",
    ]  # fmt: skip
    assert bench.percentile([], 0.5) == 0.0
    assert bench.percentile([10.0], 0.95) == 10.0
    assert bench.percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert bench.percentile([1.0, 2.0, 3.0, 4.0], 0.95) == pytest.approx(3.85)

    monkeypatch.setattr(bench.shutil, "which", lambda _: None)
    assert bench.gpu_memory_mb() is None
    monkeypatch.setattr(bench.shutil, "which", lambda _: "/usr/bin/nvidia-smi")

    class Done:
        stdout = "2048\n1024\n"

    monkeypatch.setattr(bench.subprocess, "run", lambda *a, **k: Done())
    assert bench.gpu_memory_mb() == 2048.0

    def fail(*args: object, **kwargs: object) -> None:
        raise bench.subprocess.SubprocessError("sem GPU")

    monkeypatch.setattr(bench.subprocess, "run", fail)
    assert bench.gpu_memory_mb() is None
    assert bench._fmt(None) == "-" and bench._fmt(1.23456, 2) == "1.23"
