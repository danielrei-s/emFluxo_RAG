"""Corre um parser num subprocesso isolado, com limites de tempo e memória (F3-T10, INV-12).

Toda a ingestão passa por aqui: o worker não tem rede, não lança processos e só vê um ambiente
mínimo (``sandbox_env``). O tempo de parede inclui o arranque do worker.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import psutil

from rag_core.errors import (
    CorruptedFile,
    ParseMemoryLimit,
    ParseTimeout,
    RagError,
    ValidationFailed,
)
from rag_core.ingestion.sandbox_env import sandbox_environment
from rag_core.interfaces import ParseLimits
from rag_core.types import DetectedType, StructuredDocument

__all__ = ["run_parser_sandboxed"]
POLL_INTERVAL_S = 0.2
_WORKER_MODULE = "rag_core.ingestion.sandbox_worker"


def _error_classes() -> dict[str, type[RagError]]:
    found: dict[str, type[RagError]] = {}
    pending = [RagError]
    while pending:
        cls = pending.pop()
        found[cls.code] = cls
        pending.extend(cls.__subclasses__())
    return found


def _raise_for(error: dict[str, Any]) -> None:
    cls = _error_classes().get(str(error["error"]), CorruptedFile)
    if cls is ValidationFailed:
        raise ValidationFailed(error.get("detail"), error.get("subcode"))
    raise cls(error.get("detail"))


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        parent = psutil.Process(process.pid)
        for child in parent.children(recursive=True):
            child.kill()
    except psutil.Error:
        pass
    process.kill()
    process.wait()


def _rss_bytes(pid: int) -> int:
    try:
        parent = psutil.Process(pid)
        total: int = parent.memory_info().rss
        for child in parent.children(recursive=True):
            total += int(child.memory_info().rss)
        return total
    except psutil.Error:  # o processo já terminou
        return 0


def run_parser_sandboxed(
    data: bytes,
    *,
    filename: str,
    detected: DetectedType,
    profile: str = "lite",
    limits: ParseLimits | None = None,
    test_mode: bool = False,
    artifacts_path: Path | None = None,
) -> StructuredDocument:
    """Faz o parse num subprocesso. Levanta ``RagError`` (timeout, memória, violação, ficheiro)."""
    limits = limits or ParseLimits()
    request = json.dumps(
        {
            "filename": filename,
            "detected": detected.value,
            "profile": profile,
            "limits": limits.model_dump(mode="json"),
            "data_b64": base64.b64encode(data).decode("ascii"),
            "test_mode": test_mode,
            "artifacts_path": str(artifacts_path) if artifacts_path else None,
        }
    )
    memory_limit = limits.max_memory_mb * 1024 * 1024
    with tempfile.TemporaryDirectory(prefix="rag-sandbox-", ignore_cleanup_errors=True) as cwd:
        process = subprocess.Popen(  # noqa: S603 - executável e argumentos fixos
            [sys.executable, "-I", "-m", _WORKER_MODULE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=sandbox_environment(),
            cwd=cwd,
        )
        started = time.monotonic()
        pending_input: bytes | None = request.encode("utf-8") + b"\n"
        while True:
            try:
                stdout, _ = process.communicate(input=pending_input, timeout=POLL_INTERVAL_S)
                break
            except subprocess.TimeoutExpired:
                pending_input = None
            if time.monotonic() - started > limits.timeout_s:
                _kill_tree(process)
                raise ParseTimeout()
            if _rss_bytes(process.pid) > memory_limit:
                _kill_tree(process)
                raise ParseMemoryLimit()
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise CorruptedFile("worker_crashed")
    try:
        response = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise CorruptedFile("worker_bad_response") from exc
    if "error" in response:
        _raise_for(response)
    return StructuredDocument.model_validate_json(json.dumps(response["ok"]))
