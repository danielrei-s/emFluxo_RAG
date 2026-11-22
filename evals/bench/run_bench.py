#!/usr/bin/env python3
"""Benchmark de modelos (F5-T05): qualidade, latência e memória por combinação.

Para cada combinação (embeddings, reranker e LLM) corre a avaliação no golden set com modelos
reais e mede embeddings/s, TTFT, tempo total (p50/p95) e memória (RSS e, se houver, VRAM).

    uv run python evals/bench/run_bench.py --models models.yaml \\
        --embeddings rag-embed rag-embed-e5-base --rerankers none rag-rerank \\
        --llms rag-qwen rag-mistral --out evals/bench/results-2026-12-01.md

    uv run python evals/bench/run_bench.py --dry-run     # fakes: só valida o formato do relatório
"""

from __future__ import annotations

import argparse
import itertools
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import psutil
from rag_core.config import RetrievalSettings, Settings
from rag_core.evals.runner import DEFAULT_MANIFEST, Report, run_eval
from rag_core.fakes import FakeEmbedder, FakeLLMProvider, FakeReranker
from rag_core.interfaces import Embedder, LLMProvider, Reranker
from rag_core.providers.factory import build_models

DRY_RUN_NOTE = " — ensaio com fakes"
ROOT = Path(__file__).resolve().parents[2]
SAMPLE_TEXTS = [
    f"Parágrafo {n} de teste sobre férias, preços e prazos de pagamento." for n in range(64)
]
Models = tuple[Embedder, LLMProvider, Reranker, Settings]


@dataclass(frozen=True)
class Combo:
    embedding: str
    reranker: str | None
    llm: str

    @property
    def label(self) -> str:
        return f"{self.embedding} / {self.reranker or 'sem reranker'} / {self.llm}"


@dataclass(frozen=True)
class BenchRow:
    combo: Combo
    report: Report
    embeddings_per_s: float
    total_p50_ms: float
    total_p95_ms: float
    rss_mb: float
    vram_mb: float | None


def parse_combos(
    embeddings: Sequence[str], rerankers: Sequence[str], llms: Sequence[str]
) -> list[Combo]:
    """Produto cartesiano; ``none`` significa "sem reranker"."""
    return [
        Combo(e, None if r == "none" else r, m)
        for e, r, m in itertools.product(embeddings, rerankers, llms)
    ]


def percentile(values: Sequence[float], q: float) -> float:
    """Percentil por interpolação linear (``q`` entre 0 e 1)."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * q
    low, high = int(position), min(int(position) + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def gpu_memory_mb() -> float | None:
    """Memória usada na GPU (nvidia-smi), se existir."""
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return None
    try:
        done = subprocess.run(  # noqa: S603 - executável resolvido, argumentos fixos
            [exe, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=10,
        )  # fmt: skip
        return float(done.stdout.splitlines()[0].strip())
    except (subprocess.SubprocessError, ValueError, IndexError):
        return None


def embeddings_per_second(embedder: Embedder, texts: Sequence[str] = SAMPLE_TEXTS) -> float:
    started = time.perf_counter()
    embedder.embed_documents(list(texts))
    elapsed = max(time.perf_counter() - started, 1e-9)
    return len(texts) / elapsed


def measure(
    combo: Combo,
    models: Models,
    golden: Sequence[Path],
    store_dir: Path,
    manifest: Path,
    runner: Callable[..., Any] | None = None,
) -> BenchRow:
    embedder = models[0]
    report = run_eval(
        golden, config="live", store_dir=store_dir, manifest_path=manifest, models=models,
        runner=runner,
    )  # fmt: skip
    latencies = [float(i.latency_ms) for i in report.items]
    return BenchRow(
        combo=combo,
        report=report,
        embeddings_per_s=embeddings_per_second(embedder),
        total_p50_ms=percentile(latencies, 0.5),
        total_p95_ms=percentile(latencies, 0.95),
        rss_mb=psutil.Process().memory_info().rss / (1024 * 1024),
        vram_mb=gpu_memory_mb(),
    )


def _fmt(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def render_markdown(rows: Sequence[BenchRow], day: date, dry_run: bool = False) -> str:
    """Relatório em markdown: uma linha por combinação."""
    header = (
        "| Combinação | recall@5 | mrr | contém | não-encontrei | fugas | fallback | emb/s "
        "| TTFT p50 (ms) | total p50 (ms) | total p95 (ms) | RSS (MB) | VRAM (MB) |"
    )
    lines = [
        f"# Benchmark de modelos ({day.isoformat()})" + (DRY_RUN_NOTE if dry_run else ""),
        "",
        "Golden set Aurora/Boreal; modelos reais via `models.yaml`. Sem segredos neste ficheiro.",
        "",
        header,
        "|" + "---|" * 13,
    ]
    for row in rows:
        metrics = row.report.metrics
        lines.append(
            f"| {row.combo.label} | {_fmt(metrics.recall_at_5)} | {_fmt(metrics.mrr)} "
            f"| {_fmt(metrics.answer_contains_rate)} | {_fmt(metrics.not_found_accuracy)} "
            f"| {_fmt(metrics.leak_rate)} | {_fmt(metrics.fallback_rate)} "
            f"| {_fmt(row.embeddings_per_s, 1)} | {_fmt(row.report.ttft_ms_median, 0)} "
            f"| {_fmt(row.total_p50_ms, 0)} | {_fmt(row.total_p95_ms, 0)} "
            f"| {_fmt(row.rss_mb, 0)} | {_fmt(row.vram_mb, 0)} |"
        )
    lines += ["", "Escolhas e justificação: ver `docs/adr/0009-modelos-v1.md`.", ""]
    return "\n".join(lines)


def fake_models() -> Models:
    settings = Settings.for_tests(retrieval=RetrievalSettings(min_relevance=0.05))
    return FakeEmbedder(), FakeLLMProvider("echo_cite"), FakeReranker(), settings


def run_bench(
    combos: Sequence[Combo],
    *,
    golden: Sequence[Path],
    store_dir: Path,
    manifest: Path,
    models_file: Path | None,
    dry_run: bool = False,
    runner: Callable[..., Any] | None = None,
) -> list[BenchRow]:
    rows = []
    for combo in combos:
        if dry_run:
            models = fake_models()
        else:
            built = build_models(
                Settings.from_env(), models_file, llm_alias=combo.llm,
                embedding_alias=combo.embedding, reranker_alias=combo.reranker,
            )  # fmt: skip
            models = (built.embedder, built.llm, built.reranker, built.settings)
        rows.append(measure(combo, models, golden, store_dir, manifest, runner))
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--models", type=Path, default=None, help="models.yaml")
    parser.add_argument("--golden", type=Path, default=ROOT / "evals" / "golden")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--store-dir", type=Path, default=ROOT / ".rag" / "bench")
    parser.add_argument("--embeddings", nargs="+", default=["rag-embed"])
    parser.add_argument("--rerankers", nargs="+", default=["none"])
    parser.add_argument("--llms", nargs="+", default=["rag-default"])
    parser.add_argument("--out", type=Path, default=None, help="ficheiro markdown de saída")
    parser.add_argument("--dry-run", action="store_true", help="usa fakes (valida o formato)")
    args = parser.parse_args(argv)

    golden = [args.golden] if args.golden.is_file() else sorted(args.golden.glob("*.yaml"))
    combos = parse_combos(args.embeddings, args.rerankers, args.llms)
    rows = run_bench(
        combos, golden=golden, store_dir=args.store_dir, manifest=args.manifest,
        models_file=args.models, dry_run=args.dry_run,
    )  # fmt: skip
    markdown = render_markdown(rows, date.today(), dry_run=args.dry_run)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
