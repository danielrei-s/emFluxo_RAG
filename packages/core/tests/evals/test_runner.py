"""Testes de F5-T04: execução da avaliação, relatórios e comparação com a baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from rag_core.evals.runner import (
    DEFAULT_THRESHOLDS,
    ItemResult,
    Metrics,
    Report,
    compare,
    compute_metrics,
    load_thresholds,
    run_eval,
    write_report,
)
from rag_core.testing.indexed import inproc_runner

MINI = [
    {
        "id": "A-Q001", "tenant": "aurora", "user": "ana", "category": "answerable_single",
        "question": "Quantos dias de férias tenho por ano?",
        "expected_doc_ids": ["A01"], "expected_answer_contains": ["Manual do Colaborador"],
        "must_not_contain": ["CANARIO"],
    },
    {
        "id": "A-Q030", "tenant": "aurora", "user": "ana", "category": "acl_probe",
        "question": "Qual é o salário base de um Técnico Comercial?",
        "expected_kind": "not_found", "must_not_contain": ["1350", "CANARIO-RH"],
    },
    {
        "id": "A-Q040", "tenant": "aurora", "user": "ana", "category": "followup",
        "question": "E o prazo de pagamento?",
        "history": [
            {"role": "user", "content": "Qual é o prazo de pagamento dos clientes?"},
            {"role": "assistant", "content": "É de 30 dias [1]."},
        ],
        "expected_doc_ids": ["A05"], "expected_answer_contains": ["faturação"],
    },
]  # fmt: skip


def _golden(tmp_path: Path, items: list[dict[str, Any]] | None = None) -> Path:
    path = tmp_path / "golden.yaml"
    path.write_text(yaml.safe_dump(items or MINI, allow_unicode=True), encoding="utf-8")
    return path


def test_runner_on_mini_golden(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    report = run_eval([_golden(tmp_path)], config="fake", store_dir=store_dir, runner=inproc_runner)
    assert report.config == "fake" and report.metrics.n == 3
    assert {i.id for i in report.items} == {"A-Q001", "A-Q030", "A-Q040"}
    assert set(report.by_category) == {"answerable_single", "acl_probe", "followup"}
    first = next(i for i in report.items if i.id == "A-Q001")
    assert "A01" in first.retrieved_doc_ids
    assert first.recall_at_5 == 1.0 and first.mrr is not None and first.mrr > 0
    assert report.metrics.leak_rate == 0.0
    assert report.metrics.recall_at_5 is not None and report.metrics.recall_at_5 > 0
    assert report.metrics.not_found_accuracy is not None
    assert report.ttft_ms_median is None  # só medido com modelos reais

    again = run_eval([_golden(tmp_path)], config="fake", store_dir=store_dir)  # sem runner: cache
    assert again.corpus_hash == report.corpus_hash
    assert again.metrics == report.metrics
    assert len(list(store_dir.glob("index-*.db"))) == 1

    write_report(report, tmp_path / "out")
    loaded = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert loaded["metrics"]["n"] == 3
    markdown = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "# Avaliação (fake)" in markdown and "| global | 3 |" in markdown
    assert "| acl_probe |" in markdown


def test_leak_counted(tmp_path: Path) -> None:
    leaky = [
        {
            "id": "A-Q001", "tenant": "aurora", "user": "ana", "category": "answerable_single",
            "question": "Quantos dias de férias tenho por ano?",
            "expected_doc_ids": ["A01"], "must_not_contain": ["Manual do Colaborador"],
        }
    ]  # fmt: skip
    report = run_eval(
        [_golden(tmp_path, leaky)], config="fake", store_dir=tmp_path / "s", runner=inproc_runner
    )
    assert report.items[0].leaked is True
    assert report.metrics.leak_rate == 1.0
    regressions = compare(report, {"metrics": {"leak_rate": 0.0}}, load_thresholds())
    assert [r.metric for r in regressions] == ["leak_rate"]
    # leak_rate > 0 é regressão mesmo com uma baseline que já tinha fugas
    assert compare(report, {"metrics": {"leak_rate": 1.0}}, {})[0].metric == "leak_rate"


def _report(config: str = "fake", **metrics: float | None) -> Report:
    return Report(
        config=config,  # type: ignore[arg-type]
        corpus_hash="x",
        metrics=Metrics(n=10, **metrics),
        by_category={},
        items=(),
    )


def test_compare_detects_regression() -> None:
    thresholds = load_thresholds(DEFAULT_THRESHOLDS)
    baseline = {
        "metrics": {"recall_at_5": 0.9, "mrr": 0.8, "fallback_rate": 0.05, "leak_rate": 0.0}
    }
    same = _report(recall_at_5=0.9, mrr=0.8, fallback_rate=0.05, leak_rate=0.0)
    assert compare(same, baseline, thresholds) == []
    within = _report(recall_at_5=0.89, mrr=0.79, fallback_rate=0.06, leak_rate=0.0)
    assert compare(within, baseline, thresholds) == []  # dentro da tolerância de 0,02

    worse = _report(recall_at_5=0.80, mrr=0.8, fallback_rate=0.20, leak_rate=0.0)
    found = {r.metric: r for r in compare(worse, baseline, thresholds)}
    assert set(found) == {"recall_at_5", "fallback_rate"}
    assert found["recall_at_5"].baseline == 0.9 and found["recall_at_5"].current == 0.80
    assert "queda máxima" in found["recall_at_5"].reason
    # métricas indefinidas num dos lados são ignoradas
    assert compare(_report(recall_at_5=None), baseline, thresholds) == []
    assert compare(same, {"metrics": {}}, thresholds) == []


def test_live_thresholds_set_the_m1_floors_and_ceilings() -> None:
    thresholds = load_thresholds()
    live = _report("live", recall_at_5=0.7, answer_contains_rate=0.5, fallback_rate=0.2)
    found = {r.metric for r in compare(live, {"metrics": {}}, thresholds)}
    assert found == {"recall_at_5", "answer_contains_rate", "fallback_rate"}
    good = _report("live", recall_at_5=0.85, answer_contains_rate=0.8, fallback_rate=0.05)
    assert compare(good, {"metrics": {}}, thresholds) == []
    fake_with_same_numbers = _report("fake", recall_at_5=0.7, answer_contains_rate=0.5)
    assert compare(fake_with_same_numbers, {"metrics": {}}, thresholds) == []  # sem mínimos no fake


def test_compute_metrics_and_markdown_with_regressions(tmp_path: Path) -> None:
    def item(**kw: Any) -> ItemResult:
        base: dict[str, Any] = {
            "id": "i", "category": "c", "kind": "grounded", "expected_kind": "grounded",
            "retrieved_doc_ids": (), "recall_at_5": None, "mrr": None, "ndcg_at_5": None,
            "contains_ok": None, "leaked": False, "fell_back": False, "latency_ms": 0,
        }  # fmt: skip
        return ItemResult(**{**base, **kw})

    items = [
        item(recall_at_5=1.0, mrr=1.0, ndcg_at_5=1.0, contains_ok=True),
        item(recall_at_5=0.0, mrr=0.0, ndcg_at_5=0.0, contains_ok=False, fell_back=True),
        item(expected_kind="not_found", kind="not_found"),
        item(expected_kind="not_found", kind="grounded", leaked=True),
    ]
    metrics = compute_metrics(items)
    assert (metrics.n, metrics.recall_at_5, metrics.mrr) == (4, 0.5, 0.5)
    assert metrics.answer_contains_rate == 0.5 and metrics.not_found_accuracy == 0.5
    assert metrics.fallback_rate == 0.25 and metrics.citation_validity_rate == 0.75
    assert metrics.leak_rate == 0.25
    empty = compute_metrics([])
    assert empty.n == 0 and empty.recall_at_5 is None and empty.leak_rate is None

    report = Report(
        config="live", corpus_hash="h", metrics=metrics, by_category={}, items=tuple(items),
        ttft_ms_median=420.0,
    )  # fmt: skip
    regressions = compare(report, {"metrics": {"recall_at_5": 0.9}}, load_thresholds())
    write_report(report, tmp_path, regressions)
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "TTFT mediano: 420 ms" in text and "## Regressões" in text
    assert "**leak_rate**" in text


def test_missing_golden_files_are_reported() -> None:
    with pytest.raises(FileNotFoundError):
        run_eval([Path("nao-existe.yaml")], config="fake", store_dir=Path("x"))


def test_live_config_measures_ttft_with_injected_models(tmp_path: Path) -> None:
    from rag_core.config import RetrievalSettings, Settings
    from rag_core.fakes import FakeEmbedder, FakeLLMProvider, FakeReranker

    settings = Settings.for_tests(retrieval=RetrievalSettings(min_relevance=0.05))
    models = (FakeEmbedder(), FakeLLMProvider("echo_cite"), FakeReranker(), settings)
    report = run_eval(
        [_golden(tmp_path)],
        config="live",
        store_dir=tmp_path / "live",
        runner=inproc_runner,
        models=models,
    )
    assert report.config == "live"
    assert report.ttft_ms_median is not None and report.ttft_ms_median >= 0


def test_ttft_falls_back_to_total_time_when_no_token_is_streamed(tmp_path: Path) -> None:
    from rag_core.evals.golden import GoldenItem
    from rag_core.evals.runner import _measure_ttft

    class Silent:
        def stream_answer(self, *args: Any, **kwargs: Any) -> Any:
            yield {"type": "meta", "used_chunk_ids": []}

    item = GoldenItem(id="x", tenant="aurora", user="ana", question="?", category="unanswerable")
    elapsed = _measure_ttft(Silent(), item, [], None, None, frozenset())  # type: ignore[arg-type]
    assert elapsed >= 0


def test_live_models_come_from_the_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    from rag_core.evals.runner import REPO_ROOT, _models

    monkeypatch.setenv("RAG_OLLAMA_URL", "http://127.0.0.1:11434/v1")
    embedder, llm, _, settings = _models("live", REPO_ROOT / "models.example.yaml")
    assert embedder.model_id == "rag-embed" and getattr(llm, "name", "") == "rag-default"
    assert settings.retrieval.rerank_enabled is False
