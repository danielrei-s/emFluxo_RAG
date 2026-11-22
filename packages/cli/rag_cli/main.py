"""CLI ``rag``: ingerir, perguntar, avaliar e verificar modelos (F5-T03).

Nunca imprime o prompt nem excertos; só ``--debug-ids`` mostra ``chunk_id`` (em stderr).
"""

from __future__ import annotations

import json
import secrets
from collections import Counter
from pathlib import Path
from typing import Annotated, Any, Literal

import typer
from rag_core.clock import SystemClock
from rag_core.errors import NotFound, RagError, ValidationFailed
from rag_core.evals.runner import (
    DEFAULT_MANIFEST,
    DEFAULT_THRESHOLDS,
    HIGHER_IS_BETTER,
    LOWER_IS_BETTER,
    compare,
    load_thresholds,
    run_eval,
    write_report,
)
from rag_core.generation import ChatService
from rag_core.ingestion.pipeline import IngestionService
from rag_core.interfaces import TenantPolicy
from rag_core.manifest import DEFAULT_TENANT, DEFAULT_USER, CorpusManifest
from rag_core.providers import ModelRegistry
from rag_core.retrieval import HybridRetriever
from rag_core.types import Answer, Origin

from rag_cli.wiring import DEFAULT_MODELS_FILE, build_runtime

app = typer.Typer(
    help="Plataforma RAG: ingere documentos, faz perguntas e avalia (modo local).",
    no_args_is_help=True,
    add_completion=False,
)

Db = Annotated[Path, typer.Option(help="Ficheiro SQLite do índice.")]
Tenant = Annotated[str, typer.Option(help="Tenant (empresa).")]
Workspace = Annotated[str, typer.Option(help="Workspace.")]
Manifest = Annotated[Path | None, typer.Option(help="manifest.yaml com utilizadores e ACL.")]
FakeModels = Annotated[bool, typer.Option("--fake-models", help="Usa modelos falsos (testes).")]
Models = Annotated[Path | None, typer.Option(help="models.yaml (por omissão ./models.yaml).")]
DEFAULT_DB = Path(".rag/dev.db")


def _describe(error: Exception | str) -> str:
    """Só códigos (nunca conteúdo): ``validation_failed:subcode`` para erros de validação."""
    if isinstance(error, ValidationFailed) and error.subcode:
        return f"{error}:{error.subcode}"
    return str(error)


def _fail(error: Exception | str, code: int) -> typer.Exit:
    typer.echo(f"erro: {_describe(error)}", err=True)
    return typer.Exit(code)


def _load_manifest(path: Path | None) -> CorpusManifest:
    if path is None:
        return CorpusManifest()
    if not path.is_file():
        raise _fail("manifest inexistente", 2)
    return CorpusManifest.load(path)


def _files(path: Path) -> list[tuple[Path, str]]:
    """``(ficheiro, caminho relativo)``; um ficheiro isolado conta como a sua raiz."""
    if path.is_file():
        return [(path, path.name)]
    return [(f, f.relative_to(path).as_posix()) for f in sorted(path.rglob("*")) if f.is_file()]


@app.command()
def ingest(
    path: Annotated[Path, typer.Argument(help="Ficheiro ou pasta a ingerir.")],
    tenant: Tenant = DEFAULT_TENANT,
    workspace: Workspace = "default",
    profile: Annotated[Literal["lite", "full"], typer.Option(help="Perfil de parsing.")] = "lite",
    db: Db = DEFAULT_DB,
    manifest: Manifest = None,
    fake_models: FakeModels = False,
    models: Models = None,
    docling_artifacts: Annotated[Path | None, typer.Option(help="Modelos do Docling.")] = None,
) -> None:
    """Ingere um ficheiro ou pasta (sempre pelo sandbox de parsing)."""
    if not path.exists():
        raise _fail("caminho inexistente", 2)
    try:
        cm = _load_manifest(manifest)
        runtime = build_runtime(db, fake_models=fake_models, models_file=models)
        service = IngestionService(
            registry_profile=profile,
            embedder=runtime.embedder,
            store=runtime.store,
            settings=runtime.settings,
            clock=SystemClock(),
            artifacts_path=docling_artifacts,
        )
        counts: Counter[str] = Counter()
        failures: list[str] = []
        for file, rel in _files(path):
            source = cm.source_for_file(tenant, workspace, rel, file.name)
            for result in service.ingest_file(source, file.read_bytes()):
                counts[result.status] += 1
                if result.status == "failed":
                    failures.append(f"falhou: {rel} ({result.error_code})")
    except KeyError as error:
        raise _fail(f"tenant desconhecido ({error.args[0]})", 2) from error
    except RagError as error:
        raise _fail(error, 2 if isinstance(error, ValidationFailed | NotFound) else 1) from error
    typer.echo(
        f"indexados: {counts['indexed']} | inalterados: {counts['unchanged']} "
        f"| falhados: {counts['failed']}"
    )
    for line in failures:
        typer.echo(line)


def _source_line(answer: Answer) -> list[str]:
    lines = []
    for citation in answer.citations:
        name = citation.source_uri.rsplit("/", 1)[-1].split("#")[0]
        page = f" (p. {citation.page_start})" if citation.page_start else ""
        lines.append(f"[{citation.index}] {name}{page}")
    return lines


@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="A pergunta.")],
    user: Annotated[str, typer.Option(help="Utilizador (do manifest).")] = DEFAULT_USER,
    tenant: Tenant = DEFAULT_TENANT,
    db: Db = DEFAULT_DB,
    manifest: Manifest = None,
    as_json: Annotated[bool, typer.Option("--json", help="Resposta em JSON.")] = False,
    fake_models: FakeModels = False,
    models: Models = None,
    debug_ids: Annotated[bool, typer.Option(help="Mostra os chunk_id usados (stderr).")] = False,
) -> None:
    """Responde a uma pergunta com fontes."""
    try:
        cm = _load_manifest(manifest)
        principal = cm.principal_for(tenant, user)
        runtime = build_runtime(db, fake_models=fake_models, models_file=models)
        sentinel = (
            runtime.settings.prompt_sentinel.get_secret_value()
            if runtime.settings.prompt_sentinel
            else secrets.token_hex(16)
        )
        service = ChatService(
            HybridRetriever(runtime.store, runtime.embedder, runtime.settings),
            runtime.reranker,
            runtime.llm,
            runtime.settings,
            SystemClock(),
            sentinel,
            allowed_link_domains=runtime.settings.allowed_link_domains,
        )
        answer = service.answer(
            question,
            [],
            principal,
            policy=TenantPolicy(tenant_id=principal.tenant_id),
            origins=frozenset({Origin.CENTRAL}),
        )
    except KeyError as error:
        raise _fail(f"utilizador ou tenant desconhecido ({error.args[0]})", 2) from error
    except RagError as error:
        raise _fail(error, 2 if isinstance(error, ValidationFailed | NotFound) else 1) from error
    if as_json:
        typer.echo(answer.model_dump_json(indent=2))
    else:
        typer.echo(answer.text)
        sources = _source_line(answer)
        if sources:
            typer.echo("\nFontes:")
            for line in sources:
                typer.echo(line)
    if debug_ids:
        typer.echo("chunk_ids: " + ", ".join(answer.used_chunk_ids), err=True)


def _golden_files(path: Path) -> list[Path]:
    if not path.exists():
        raise _fail("golden set inexistente", 2)
    return [path] if path.is_file() else sorted(path.glob("*.yaml"))


@app.command(name="eval")
def eval_command(
    golden: Annotated[Path, typer.Option(help="Golden set (ficheiro YAML ou pasta).")] = Path(
        "evals/golden"
    ),
    report: Annotated[Path, typer.Option(help="Pasta do relatório.")] = Path("out/eval"),
    fake_models: FakeModels = False,
    models: Models = None,
    baseline: Annotated[Path | None, typer.Option(help="Baseline JSON a comparar.")] = None,
    thresholds: Annotated[Path, typer.Option(help="Limiares (YAML).")] = DEFAULT_THRESHOLDS,
    store_dir: Annotated[Path, typer.Option(help="Pasta da cache do índice.")] = Path(".rag/eval"),
    manifest: Annotated[Path, typer.Option(help="manifest.yaml do corpus.")] = DEFAULT_MANIFEST,
    write_baseline: Annotated[Path | None, typer.Option(help="Grava a baseline aqui.")] = None,
) -> None:
    """Avalia no golden set; sai com 1 se houver regressões (leak_rate > 0 é sempre uma)."""
    if not manifest.is_file():
        raise _fail("manifest inexistente", 2)
    try:
        result = run_eval(
            _golden_files(golden),
            config="fake" if fake_models else "live",
            store_dir=store_dir,
            manifest_path=manifest,
            models_file=models,
        )
        base: dict[str, Any] = {}
        if baseline is not None:
            if not baseline.is_file():
                raise _fail("baseline inexistente", 2)
            base = json.loads(baseline.read_text(encoding="utf-8"))
        regressions = compare(result, base, load_thresholds(thresholds))
    except RagError as error:
        raise _fail(error, 2 if isinstance(error, ValidationFailed | NotFound) else 1) from error
    write_report(result, report, regressions)
    if write_baseline is not None:
        write_baseline.parent.mkdir(parents=True, exist_ok=True)
        payload = {"config": result.config, "metrics": result.metrics.model_dump()}
        write_baseline.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    metrics = result.metrics
    typer.echo(f"itens: {metrics.n} | relatório: {report / 'report.md'}")
    for name in (*HIGHER_IS_BETTER, *LOWER_IS_BETTER):
        value = getattr(metrics, name)
        typer.echo(f"{name}: {'-' if value is None else f'{value:.3f}'}")
    for regression in regressions:
        typer.echo(f"regressão: {regression.metric} ({regression.reason})", err=True)
    if regressions:
        raise typer.Exit(1)


models_app = typer.Typer(help="Comandos sobre o registo de modelos.", no_args_is_help=True)
app.add_typer(models_app, name="models")


@models_app.command("check")
def models_check(
    models: Annotated[Path, typer.Option(help="models.yaml a verificar.")] = DEFAULT_MODELS_FILE,
    cache_dir: Annotated[Path | None, typer.Option(help="Pasta dos ficheiros de modelos.")] = None,
) -> None:
    """Valida licenças e revisões; com ``--cache-dir`` confirma também os hashes (INV-21/22)."""
    if not models.is_file():
        raise _fail("models.yaml inexistente", 2)
    try:
        registry = ModelRegistry.from_file(models)
        for alias in registry.aliases:
            spec = registry.get(alias)
            if cache_dir is not None and spec.files:
                registry.verify_files(alias, cache_dir)
            typer.echo(f"ok: {alias} ({spec.kind}, {spec.backend}, {spec.license})")
    except RagError as error:
        raise _fail(error, 2) from error
    except ValueError as error:  # esquema inválido (pydantic)
        raise _fail(f"models.yaml inválido ({type(error).__name__})", 2) from error
