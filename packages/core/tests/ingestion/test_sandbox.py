"""Testes de F3-T10: sandbox de parsing (subprocesso com limites; INV-12, INV-13)."""

from __future__ import annotations

import subprocess
import time
from typing import Any

import pytest
from rag_core.errors import (
    CorruptedFile,
    ParseMemoryLimit,
    ParseTimeout,
    SandboxViolation,
    UnsupportedType,
    ValidationFailed,
)
from rag_core.ingestion import sandbox, sandbox_worker
from rag_core.ingestion.sandbox import run_parser_sandboxed
from rag_core.ingestion.sandbox_env import sandbox_environment
from rag_core.interfaces import ParseLimits
from rag_core.testing import corpus
from rag_core.types import DetectedType


def _run(detected: DetectedType, filename: str, data: bytes = b"x", **kwargs: Any) -> Any:
    kwargs.setdefault("test_mode", True)
    return run_parser_sandboxed(data, filename=filename, detected=detected, **kwargs)


# ------------------------------------------------------------------------ INV-12


@pytest.mark.parametrize("action", ["connect", "bind", "dns", "swallow"])
def test_inv12_network_blocked_in_worker(action: str) -> None:
    with pytest.raises(SandboxViolation):
        _run(DetectedType.MSG, f"{action}.txt")


def test_network_probe_without_attempt_runs_normally() -> None:
    doc = _run(DetectedType.MSG, "nada.txt")
    assert doc.blocks[0].text == "rede acessível"


@pytest.mark.parametrize("action", ["subprocess", "system", "exec", "spawn"])
def test_inv12_process_spawn_blocked(action: str) -> None:
    with pytest.raises(SandboxViolation):
        _run(DetectedType.TIFF, f"{action}.txt")


def test_test_parsers_are_not_registered_without_test_mode() -> None:
    with pytest.raises(UnsupportedType):
        _run(DetectedType.MSG, "connect.txt", test_mode=False)


def test_audit_hook_blocks_only_dangerous_events() -> None:
    violations: list[str] = []
    hook = sandbox_worker.make_audit_hook(violations)
    hook("open", ("ficheiro", "r", 0))  # eventos normais passam
    hook("import", ("modulo",))
    assert violations == []
    for event in sandbox_worker.BLOCKED_EVENTS:
        with pytest.raises(PermissionError):
            hook(event, ())
    assert len(violations) == len(sandbox_worker.BLOCKED_EVENTS)
    assert {"socket.connect", "socket.bind", "socket.getaddrinfo", "subprocess.Popen"} <= set(
        violations
    )
    assert {"os.system", "os.exec", "os.posix_spawn", "os.spawn"} <= set(violations)


# --------------------------------------------------------------- tempo e memória


def test_timeout_kills_worker() -> None:
    started = time.monotonic()
    with pytest.raises(ParseTimeout):
        _run(DetectedType.PNG, "dorme.png", limits=ParseLimits(timeout_s=3))
    assert time.monotonic() - started < 3 + 2


def test_memory_limit_kills_worker() -> None:
    started = time.monotonic()
    with pytest.raises(ParseMemoryLimit):
        _run(
            DetectedType.JPEG,
            "come.jpg",
            limits=ParseLimits(max_memory_mb=700, timeout_s=60),
        )
    assert time.monotonic() - started < 40


# ------------------------------------------------------------------------ INV-13


def test_inv13_worker_env_has_no_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_SUPABASE_SERVICE_ROLE_KEY", "CANARIO-INV13-A")
    monkeypatch.setenv("OPENAI_API_KEY", "CANARIO-INV13-B")
    doc = _run(DetectedType.XLSX, "env.xlsx")
    dump = doc.blocks[0].text
    assert "RAG_SUPABASE_SERVICE_ROLE_KEY" not in dump
    assert "OPENAI_API_KEY" not in dump
    assert "CANARIO-INV13-A" not in dump
    assert "CANARIO-INV13-B" not in dump
    names = dump.split("\n---\n")[0].split("\n")
    assert not any(n.startswith("RAG_") for n in names)
    assert {n.upper() for n in names} <= {k.upper() for k in sandbox_environment()} | {
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "SYSTEMROOT",
        "PATH",
        "SYSTEMDRIVE",
        "WINDIR",
        "LC_CTYPE",
        "PYTHONIOENCODING",
        "PYVENV_LAUNCHER",
        "__PYVENV_LAUNCHER__",
    }


# ------------------------------------------------------------ parsers reais e erros


def test_roundtrip_with_real_lite_parser() -> None:
    doc = run_parser_sandboxed(
        corpus.read_bytes("A02"), filename="politica_despesas.docx", detected=DetectedType.DOCX
    )
    assert doc.title == "Política de Despesas"
    assert doc.blocks[0].text == "Política de Despesas"
    assert doc.blocks[-1].rows is not None
    assert doc.parser_name == "lite-docx"


def test_roundtrip_preserves_attachments_bytes() -> None:
    raw = corpus.read_bytes("A06")
    doc = run_parser_sandboxed(raw, filename="email.eml", detected=DetectedType.EML)
    (attachment,) = doc.attachments
    assert attachment.filename == "condicoes.pdf"
    assert attachment.data.startswith(b"%PDF-")
    assert doc.meta == {"email_from_domain": "papelaria-norte.example"}


def test_parser_errors_cross_the_process_boundary_with_their_codes() -> None:
    with pytest.raises(CorruptedFile):
        run_parser_sandboxed(b"PK\x03\x04lixo", filename="x.docx", detected=DetectedType.DOCX)
    with pytest.raises(ValidationFailed) as exc:
        run_parser_sandboxed(
            corpus.read_bytes("A01"),
            filename="m.pdf",
            detected=DetectedType.PDF,
            limits=ParseLimits(max_pages=1),
        )
    assert exc.value.subcode == "too_many_pages"


def test_handle_request_reports_unexpected_exceptions_and_memory_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    request: dict[str, Any] = {
        "filename": "f.txt",
        "detected": "txt",
        "profile": "lite",
        "limits": ParseLimits().model_dump(mode="json"),
        "data_b64": "b2xh",
    }
    ok = json.loads(sandbox_worker.handle_request(request, []))
    assert ok["ok"]["blocks"][0]["text"] == "ola"

    def raise_memory(_request: dict[str, Any]) -> Any:
        raise MemoryError

    monkeypatch.setattr(sandbox_worker, "_registry", raise_memory)
    assert json.loads(sandbox_worker.handle_request(request, []))["error"] == "parse_memory_limit"

    def raise_other(_request: dict[str, Any]) -> Any:
        raise ValueError("falha")

    monkeypatch.setattr(sandbox_worker, "_registry", raise_other)
    assert json.loads(sandbox_worker.handle_request(request, []))["error"] == "corrupted_file"
    violated = json.loads(sandbox_worker.handle_request(request, ["socket.connect"]))
    assert violated["error"] == "sandbox_violation"


def test_handle_request_builds_the_full_profile_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from rag_core.parsing import docling_full

    monkeypatch.setattr(docling_full, "_supported_types", lambda: frozenset({DetectedType.PDF}))
    registry = sandbox_worker._registry(
        {
            "profile": "full",
            "limits": ParseLimits().model_dump(mode="json"),
            "artifacts_path": str(tmp_path),
        }
    )
    assert registry.profile == "full"


def test_worker_crash_and_garbage_output_are_corrupted_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    def fake_worker(code: str) -> list[str]:
        return [sys.executable, "-I", "-c", code]

    real_popen = subprocess.Popen

    def popen_with(code: str) -> Any:
        def factory(_args: list[str], **kwargs: Any) -> Any:
            return real_popen(fake_worker(code), **kwargs)

        return factory

    for code in ("import sys; sys.exit(3)", "print('isto nao e json')"):
        monkeypatch.setattr(subprocess, "Popen", popen_with(code))
        with pytest.raises(CorruptedFile):
            run_parser_sandboxed(b"x", filename="f.txt", detected=DetectedType.TXT)


def _request(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "filename": "f.txt",
        "detected": "txt",
        "profile": "lite",
        "limits": ParseLimits().model_dump(mode="json"),
        "data_b64": "b2xh",
    }
    return {**base, **overrides}


def test_handle_request_maps_rag_errors_with_subcode() -> None:
    import json

    bad_pdf = _request(detected="pdf", filename="f.pdf", data_b64="JVBERi0xLjQgbGl4bw==")
    assert json.loads(sandbox_worker.handle_request(bad_pdf, []))["error"] == "corrupted_file"
    pages = _request(
        detected="pdf",
        filename="m.pdf",
        data_b64=__import__("base64").b64encode(corpus.read_bytes("A01")).decode(),
        limits=ParseLimits(max_pages=1).model_dump(mode="json"),
    )
    response = json.loads(sandbox_worker.handle_request(pages, []))
    assert (response["error"], response["subcode"]) == ("validation_failed", "too_many_pages")


def test_worker_registry_ocr_fallback_and_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from rag_core.parsing import ocr

    def not_installed() -> Any:
        raise UnsupportedType("ocr_not_installed")

    monkeypatch.setattr(ocr, "RapidOcrEngine", not_installed)
    ocr_on = ParseLimits(ocr=True).model_dump(mode="json")
    registry = sandbox_worker._registry(_request(limits=ocr_on, test_mode=True))
    assert registry.get(DetectedType.PDF).name == "lite-pdf"
    assert registry.get(DetectedType.MSG).name == "test-network-probe"
    assert sandbox_worker._registry(_request()).profile == "lite"
    with pytest.raises(UnsupportedType):
        sandbox_worker._registry(_request()).get(DetectedType.MSG)


def test_kill_tree_tolerates_an_already_finished_process() -> None:
    import sys

    process = subprocess.Popen([sys.executable, "-I", "-c", "pass"])
    process.wait()
    sandbox._kill_tree(process)
    assert process.returncode == 0


def test_rss_of_a_missing_process_is_zero() -> None:
    import os

    assert sandbox._rss_bytes(2**22 + 12345) == 0
    assert sandbox._rss_bytes(os.getpid()) > 0
