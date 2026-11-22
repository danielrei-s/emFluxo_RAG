"""Worker de parsing: corre num subprocesso isolado (``python -I -m ...sandbox_worker``).

Protocolo: o pai envia uma linha JSON no ``stdin`` (``filename``, ``detected``, ``profile``,
``limits``, ``data_b64``, ``test_mode``, ``artifacts_path``); o worker responde numa linha com
``{"ok": <StructuredDocument>}`` ou ``{"error": "<code>", "detail": ..., "subcode": ...}``.

Antes de importar parsers instala-se um *audit hook* que bloqueia rede e lançamento de processos
(INV-12). Um parser que apanhe e engula o ``PermissionError`` não esconde a violação: o worker
regista-a e responde ``sandbox_violation`` de qualquer forma.
"""

from __future__ import annotations

import base64
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

BLOCKED_EVENTS = frozenset(
    {
        "socket.connect",
        "socket.bind",
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.gethostbyname_ex",
        "socket.gethostbyaddr",
        "socket.getnameinfo",
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.spawn",
    }
)
MAX_OPEN_FILES = 256


def make_audit_hook(violations: list[str]) -> Callable[[str, tuple[Any, ...]], None]:
    """Hook que levanta ``PermissionError`` nos eventos bloqueados e regista a violação."""

    def hook(event: str, args: tuple[Any, ...]) -> None:
        if event in BLOCKED_EVENTS:
            violations.append(event)
            raise PermissionError(f"sandbox: evento bloqueado ({event})")

    return hook


def _error(code: str, detail: str | None = None, subcode: str | None = None) -> str:
    return json.dumps({"error": code, "detail": detail, "subcode": subcode})


def _registry(request: dict[str, Any]) -> Any:
    from rag_core.interfaces import ParseLimits
    from rag_core.parsing.lite import lite_registry

    limits = ParseLimits.model_validate(request["limits"])
    if request["profile"] == "full":
        from rag_core.parsing.docling_full import full_registry

        registry = full_registry(Path(request["artifacts_path"]))
    else:
        engine = None
        if limits.ocr:
            from rag_core.errors import UnsupportedType
            from rag_core.parsing.ocr import RapidOcrEngine

            try:
                engine = RapidOcrEngine()
            except UnsupportedType:  # OCR não instalado: as páginas ficam com needs_ocr
                engine = None
        registry = lite_registry(engine)
    if request.get("test_mode"):
        from rag_core.testing.sandbox_parsers import register_test_parsers

        register_test_parsers(registry)
    return registry


def handle_request(request: dict[str, Any], violations: list[str]) -> str:
    """Executa o parse pedido e devolve a linha de resposta (sem I/O próprio)."""
    from rag_core.errors import RagError, ValidationFailed
    from rag_core.interfaces import ParseLimits
    from rag_core.types import DetectedType

    try:
        registry = _registry(request)
        detected = DetectedType(request["detected"])
        document = registry.get(detected).parse(
            base64.b64decode(request["data_b64"]),
            filename=request["filename"],
            detected=detected,
            limits=ParseLimits.model_validate(request["limits"]),
        )
        response = '{"ok": ' + str(document.model_dump_json()) + "}"
    except RagError as exc:
        subcode = exc.subcode if isinstance(exc, ValidationFailed) else None
        response = _error(exc.code, exc.detail_id, subcode)
    except MemoryError:
        response = _error("parse_memory_limit")
    except Exception:  # um parser nunca deve derrubar o worker sem resposta
        response = _error("corrupted_file", "worker_exception")
    if violations:  # mesmo que o parser tenha engolido o PermissionError
        return _error("sandbox_violation", violations[0])
    return response


def _apply_rlimits(limits: dict[str, Any]) -> None:  # pragma: no cover - só em POSIX
    if sys.platform == "win32":
        return
    import math
    import resource

    memory = int(limits["max_memory_mb"]) * 1024 * 1024
    cpu = math.ceil(float(limits["timeout_s"])) + 1
    for name, value in (
        ("RLIMIT_AS", memory),
        ("RLIMIT_CPU", cpu),
        ("RLIMIT_NOFILE", MAX_OPEN_FILES),
    ):
        _, hard = resource.getrlimit(getattr(resource, name))
        if hard != resource.RLIM_INFINITY:
            value = min(value, hard)
        resource.setrlimit(getattr(resource, name), (value, value))


def main() -> None:  # pragma: no cover - corre no subprocesso (testado via sandbox.py)
    out = sys.stdout.buffer
    sys.stdout = sys.stderr  # nenhuma biblioteca pode poluir o canal de resposta
    request = json.loads(sys.stdin.buffer.readline())
    _apply_rlimits(request["limits"])
    violations: list[str] = []
    sys.addaudithook(make_audit_hook(violations))
    out.write(handle_request(request, violations).encode("utf-8") + b"\n")
    out.flush()


if __name__ == "__main__":  # pragma: no cover
    main()
