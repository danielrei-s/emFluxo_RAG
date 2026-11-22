"""Execução da avaliação no golden set e comparação com a baseline (F5-T04)."""

from __future__ import annotations

import json
import sqlite3
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

import yaml

from rag_core.clock import SystemClock
from rag_core.config import RetrievalSettings, Settings
from rag_core.evals import metrics as m
from rag_core.evals.golden import GoldenItem, load_golden
from rag_core.fakes import FakeEmbedder, FakeLLMProvider, FakeReranker
from rag_core.generation import ChatService
from rag_core.generation.query import retrieval_query
from rag_core.ids import sha256_hex
from rag_core.ingestion.pipeline import IngestionService
from rag_core.interfaces import Embedder, LLMProvider, Reranker, TenantPolicy
from rag_core.manifest import CorpusManifest
from rag_core.providers.factory import build_models
from rag_core.retrieval import HybridRetriever
from rag_core.stores import SqliteVectorStore
from rag_core.types import AccessFilter, Frozen, Origin

EvalConfig = Literal["fake", "live"]
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_MANIFEST = REPO_ROOT / "fixtures" / "corpus" / "manifest.yaml"
DEFAULT_THRESHOLDS = REPO_ROOT / "evals" / "thresholds.yaml"
RETRIEVAL_K = 5
TTFT_SAMPLES = 5
HIGHER_IS_BETTER = (
    "recall_at_5",
    "mrr",
    "ndcg_at_5",
    "citation_validity_rate",
    "not_found_accuracy",
    "answer_contains_rate",
)
LOWER_IS_BETTER = ("fallback_rate", "leak_rate")


class ItemResult(Frozen):
    id: str
    category: str
    kind: str
    expected_kind: str
    retrieved_doc_ids: tuple[str, ...]
    recall_at_5: float | None
    mrr: float | None
    ndcg_at_5: float | None
    contains_ok: bool | None
    leaked: bool
    fell_back: bool
    latency_ms: int


class Metrics(Frozen):
    n: int
    recall_at_5: float | None = None
    mrr: float | None = None
    ndcg_at_5: float | None = None
    citation_validity_rate: float | None = None
    fallback_rate: float | None = None
    not_found_accuracy: float | None = None
    answer_contains_rate: float | None = None
    leak_rate: float | None = None


class Report(Frozen):
    config: EvalConfig
    corpus_hash: str
    metrics: Metrics
    by_category: dict[str, Metrics]
    items: tuple[ItemResult, ...]
    ttft_ms_median: float | None = None


class Regression(Frozen):
    metric: str
    baseline: float | None
    current: float
    reason: str


def _mean(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def compute_metrics(items: Sequence[ItemResult]) -> Metrics:
    """Agrega as métricas de um conjunto de itens."""
    contains = [i.contains_ok for i in items if i.contains_ok is not None]
    not_found = [i.kind for i in items if i.expected_kind == "not_found"]
    return Metrics(
        n=len(items),
        recall_at_5=_mean([i.recall_at_5 for i in items]),
        mrr=_mean([i.mrr for i in items]),
        ndcg_at_5=_mean([i.ndcg_at_5 for i in items]),
        citation_validity_rate=m.citation_validity_rate([i.fell_back for i in items])
        if items
        else None,
        fallback_rate=m.fallback_rate([i.fell_back for i in items]) if items else None,
        not_found_accuracy=m.not_found_accuracy(not_found) if not_found else None,
        answer_contains_rate=m.answer_contains_rate(contains) if contains else None,
        leak_rate=m.leak_rate([i.leaked for i in items]) if items else None,
    )


# ---------------------------------------------------------------------------- corpus


def _corpus_hash(manifest_path: Path, embedder_id: str, profile: str) -> str:
    return sha256_hex(manifest_path.read_bytes() + f"|{embedder_id}|{profile}".encode())[:16]


def _ingest_corpus(
    manifest: CorpusManifest,
    manifest_path: Path,
    store: SqliteVectorStore,
    embedder: Embedder,
    settings: Settings,
    runner: Callable[..., Any] | None,
) -> dict[str, str]:
    """Ingere os documentos do manifest; devolve ``doc_id interno -> id do manifest``."""
    kwargs: dict[str, Any] = {"runner": runner} if runner else {}
    service = IngestionService(
        embedder=embedder, store=store, settings=settings, clock=SystemClock(), **kwargs
    )
    mapping: dict[str, str] = {}
    for entry in manifest.data["documents"]:
        source = manifest.source_for_id(entry["id"])
        data = (manifest_path.parent / entry["file"]).read_bytes()
        for result in service.ingest_file(source, data):  # o anexo conta como o documento pai
            mapping[result.doc_id] = entry["id"]
    return mapping


def _open_store(store_dir: Path, key: str, dim: int) -> tuple[SqliteVectorStore, Path, Path]:
    store_dir.mkdir(parents=True, exist_ok=True)
    db, mapping_file = store_dir / f"index-{key}.db", store_dir / f"index-{key}.map.json"
    return SqliteVectorStore(lambda: sqlite3.connect(db), dim=dim), db, mapping_file


# ----------------------------------------------------------------------------- runner


def _models(
    config: EvalConfig, models_file: Path | None
) -> tuple[Embedder, LLMProvider, Reranker, Settings]:
    if config == "fake":
        settings = Settings.for_tests(retrieval=RetrievalSettings(min_relevance=0.05))
        return FakeEmbedder(), FakeLLMProvider("echo_cite"), FakeReranker(), settings
    built = build_models(Settings.from_env(), models_file)
    return built.embedder, built.llm, built.reranker, built.settings


def run_eval(
    golden_paths: Sequence[Path],
    *,
    config: EvalConfig,
    store_dir: Path,
    manifest_path: Path = DEFAULT_MANIFEST,
    models_file: Path | None = None,
    runner: Callable[..., Any] | None = None,
    models: tuple[Embedder, LLMProvider, Reranker, Settings] | None = None,
) -> Report:
    """Ingere o corpus (em cache pelo seu hash), corre cada item e agrega as métricas."""
    items_in: list[GoldenItem] = [i for p in golden_paths for i in load_golden(p)]
    embedder, llm, reranker, settings = models or _models(config, models_file)
    manifest = CorpusManifest.load(manifest_path)
    key = _corpus_hash(manifest_path, embedder.model_id, config)
    store, _, mapping_file = _open_store(store_dir, key, embedder.dim)
    if mapping_file.is_file():
        mapping: dict[str, str] = json.loads(mapping_file.read_text(encoding="utf-8"))
    else:
        mapping = _ingest_corpus(manifest, manifest_path, store, embedder, settings, runner)
        mapping_file.write_text(json.dumps(mapping), encoding="utf-8")

    retriever = HybridRetriever(store, embedder, settings)
    service = ChatService(retriever, reranker, llm, settings, SystemClock(), "SENTINELA-EVAL", ())
    results: list[ItemResult] = []
    ttfts: list[float] = []
    for index, item in enumerate(items_in):
        principal = manifest.principal_for(item.tenant, item.user)
        history = [] if item.history is None else list(item.history)
        origins = frozenset({Origin.CENTRAL})
        flt = AccessFilter.for_principal(principal, origins=origins)
        query = retrieval_query(item.question, history)
        retrieved: list[str] = []
        for hit in retriever.retrieve(query, flt):
            doc = mapping.get(hit.chunk.metadata.doc_id, hit.chunk.metadata.doc_id)
            if doc not in retrieved:
                retrieved.append(doc)
        policy = TenantPolicy(tenant_id=principal.tenant_id)
        answer = service.answer(item.question, history, principal, policy=policy, origins=origins)
        if config == "live" and index < TTFT_SAMPLES:
            ttfts.append(_measure_ttft(service, item, history, principal, policy, origins))
        expected = set(item.expected_doc_ids)
        results.append(
            ItemResult(
                id=item.id,
                category=item.category,
                kind=answer.kind,
                expected_kind=item.expected_kind,
                retrieved_doc_ids=tuple(retrieved),
                recall_at_5=m.recall_at_k(retrieved, expected, RETRIEVAL_K) if expected else None,
                mrr=m.mrr(retrieved, expected) if expected else None,
                ndcg_at_5=m.ndcg_at_k(retrieved, expected, RETRIEVAL_K) if expected else None,
                contains_ok=(
                    m.answer_contains(answer.text, item.expected_answer_contains)
                    if item.expected_kind == "grounded" and item.expected_answer_contains
                    else None
                ),
                leaked=m.leaks(answer.text, item.must_not_contain),
                fell_back="citation_validation_failed" in answer.warnings,
                latency_ms=answer.timings_ms.get("total", 0),
            )
        )
    by_category: dict[str, list[ItemResult]] = defaultdict(list)
    for result in results:
        by_category[result.category].append(result)
    return Report(
        config=config,
        corpus_hash=key,
        metrics=compute_metrics(results),
        by_category={c: compute_metrics(r) for c, r in sorted(by_category.items())},
        items=tuple(results),
        ttft_ms_median=m.median(ttfts) if ttfts else None,
    )


def _measure_ttft(
    service: ChatService, item: GoldenItem, history: list[Any], principal: Any, policy: Any,
    origins: frozenset[Origin],
) -> float:  # fmt: skip
    started = time.perf_counter()
    for event in service.stream_answer(
        item.question, history, principal, policy=policy, origins=origins
    ):
        if event["type"] == "token":
            return (time.perf_counter() - started) * 1000
    return (time.perf_counter() - started) * 1000


# ------------------------------------------------------------------------- relatórios


def write_report(report: Report, directory: Path, regressions: Sequence[Regression] = ()) -> None:
    """Escreve ``report.json`` e ``report.md``."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    names = (*HIGHER_IS_BETTER, *LOWER_IS_BETTER)

    def row(label: str, metrics: Metrics) -> str:
        cells = [
            f"{getattr(metrics, n):.3f}" if getattr(metrics, n) is not None else "-" for n in names
        ]
        return f"| {label} | {metrics.n} | " + " | ".join(cells) + " |"

    lines = [
        f"# Avaliação ({report.config})",
        "",
        f"Corpus: `{report.corpus_hash}`"
        + (f" · TTFT mediano: {report.ttft_ms_median:.0f} ms" if report.ttft_ms_median else ""),
        "",
        "| Âmbito | n | " + " | ".join(names) + " |",
        "|---|---|" + "---|" * len(names),
        row("global", report.metrics),
        *(row(category, metrics) for category, metrics in report.by_category.items()),
        "",
    ]
    if regressions:
        lines += ["## Regressões", "", *(f"- **{r.metric}**: {r.reason}" for r in regressions), ""]
    (directory / "report.md").write_text("\n".join(lines), encoding="utf-8")


def load_thresholds(path: Path = DEFAULT_THRESHOLDS) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def _regression(name: str, before: float | None, value: float, reason: str) -> Regression:
    return Regression(metric=name, baseline=before, current=value, reason=reason)


def compare(
    report: Report, baseline: dict[str, Any], thresholds: dict[str, Any]
) -> list[Regression]:
    """Regressões face à baseline e aos limiares; ``leak_rate`` > 0 é sempre regressão."""
    regressions: list[Regression] = []
    current = report.metrics.model_dump()
    base = baseline.get("metrics", baseline)
    max_drop = float(thresholds.get("common", {}).get("max_drop", 0.02))
    if current["leak_rate"]:
        value = current["leak_rate"]
        regressions.append(
            _regression(
                "leak_rate", base.get("leak_rate"), value, f"há fugas ({value:.3f}); o limite é 0"
            )
        )
    for name in HIGHER_IS_BETTER:
        value, before = current[name], base.get(name)
        if value is not None and before is not None and value < before - max_drop:
            reason = f"{value:.3f} < baseline {before:.3f} (queda máxima {max_drop})"
            regressions.append(_regression(name, before, value, reason))
    value, before = current["fallback_rate"], base.get("fallback_rate")
    if value is not None and before is not None and value > before + max_drop:
        reason = f"{value:.3f} > baseline {before:.3f} (subida máxima {max_drop})"
        regressions.append(_regression("fallback_rate", before, value, reason))
    section = thresholds.get(report.config, {})
    for name, floor in section.get("floors", {}).items():
        value = current.get(name)
        if value is not None and value < floor:
            reason = f"{value:.3f} abaixo do mínimo {floor}"
            regressions.append(_regression(name, base.get(name), value, reason))
    for name, ceiling in section.get("ceilings", {}).items():
        value = current.get(name)
        if value is not None and value > ceiling:
            reason = f"{value:.3f} acima do máximo {ceiling}"
            regressions.append(_regression(name, base.get(name), value, reason))
    return regressions
