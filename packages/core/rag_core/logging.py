"""Logging JSON que garante INV-03 (zero conteúdo nos logs).

Pipeline (a ordem importa): contexto → nível → timestamp → serviço → ``safe_exc_info`` →
``content_free_filter`` → renderer JSON. O logging da stdlib (uvicorn, bibliotecas) passa
exatamente pelo mesmo pipeline.
"""

from __future__ import annotations

import logging as _stdlib_logging
import re
import sys
import traceback
from collections.abc import Callable, MutableMapping
from types import TracebackType
from typing import IO, Any, cast

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

#: Chaves permitidas (C12) mais as que o próprio pipeline acrescenta.
ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "ts",
        "level",
        "event",
        "service",
        "request_id",
        "tenant_id",
        "user_id",
        "device_id",
        "doc_id",
        "chunk_id",
        "job_id",
        "conversation_id",
        "workspace_id",
        "model",
        "status",
        "error_code",
        "exc_type",
        "duration_ms",
        "ttft_ms",
        "count",
        "bytes",
        "tokens_in",
        "tokens_out",
        "hash",
        "stage",
        "attempt",
        "http_status",
        "route",
        # acrescentadas pelo pipeline
        "dropped_keys",
        "exc_frames",
    }
)

_EVENT_RE = re.compile(r"[a-z0-9_.]+")
INVALID_EVENT_NAME = "invalid_event_name"

ExcInfo = tuple[type[BaseException], BaseException, TracebackType | None]


def content_free_filter(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Remove chaves fora da allowlist e valida o nome do evento (INV-03)."""
    cleaned: EventDict = {}
    dropped = 0
    for key, value in event_dict.items():
        if key in ALLOWED_KEYS or key.startswith("_"):  # "_*" é metadados do structlog
            cleaned[key] = value
        else:
            dropped += 1
    event = cleaned.get("event")
    if not isinstance(event, str) or _EVENT_RE.fullmatch(event) is None:
        cleaned["event"] = INVALID_EVENT_NAME
    if dropped:
        cleaned["dropped_keys"] = dropped
    return cleaned


def _resolve_exc_info(event_dict: MutableMapping[str, Any]) -> ExcInfo | None:
    raw = event_dict.pop("exc_info", None)
    if raw is None or raw is False:
        record = event_dict.get("_record")
        raw = getattr(record, "exc_info", None)
    if raw is True:
        raw = sys.exc_info()
    if isinstance(raw, BaseException):
        return (type(raw), raw, raw.__traceback__)
    if isinstance(raw, tuple) and len(raw) == 3 and raw[0] is not None:
        return cast("ExcInfo", raw)
    return None


def _basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def make_safe_exc_info(tracebacks: bool) -> Processor:
    """Cria o processador que regista ``exc_type`` (e frames), nunca a mensagem."""

    def safe_exc_info(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
        info = _resolve_exc_info(event_dict)
        event_dict.pop("exception", None)
        event_dict.pop("stack_info", None)
        if info is not None:
            event_dict["exc_type"] = info[0].__name__
            if tracebacks and info[2] is not None:
                frames = traceback.extract_tb(info[2])
                event_dict["exc_frames"] = [f"{_basename(f.filename)}:{f.lineno}" for f in frames]
        return event_dict

    return safe_exc_info


def _add_service(service: str) -> Processor:
    def add_service(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
        event_dict.setdefault("service", service)
        return event_dict

    return add_service


def build_shared_processors(service: str, tracebacks: bool = False) -> list[Processor]:
    """Processadores comuns a loggers structlog e a registos da stdlib."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        _add_service(service),
        make_safe_exc_info(tracebacks),
        content_free_filter,
    ]


def _sink_processor(sink: Callable[[dict[str, Any]], None]) -> Processor:
    def capture(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
        sink(dict(event_dict))
        return event_dict

    return capture


_HANDLER_MARK = "_rag_core_handler"


def configure_logging(
    service: str,
    level: str = "INFO",
    tracebacks: bool = False,
    *,
    stream: IO[str] | None = None,
    sink: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Configura structlog e o logging da stdlib para JSON sem conteúdo.

    ``stream`` (por omissão ``stderr``) recebe uma linha JSON por evento; ``sink`` (testes)
    recebe cada evento já processado. Chamar de novo reconfigura sem duplicar handlers.
    """
    shared = build_shared_processors(service, tracebacks)
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    final: list[Processor] = [structlog.stdlib.ProcessorFormatter.remove_processors_meta]
    if sink is not None:
        final.append(_sink_processor(sink))
    final.append(structlog.processors.JSONRenderer())
    formatter = structlog.stdlib.ProcessorFormatter(foreign_pre_chain=shared, processors=final)
    handler = _stdlib_logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(formatter)
    setattr(handler, _HANDLER_MARK, True)

    root = _stdlib_logging.getLogger()
    reset_logging_handlers()
    root.addHandler(handler)
    root.setLevel(_stdlib_logging.getLevelName(level.upper()))


def reset_logging_handlers() -> None:
    """Remove os handlers instalados por ``configure_logging``."""
    root = _stdlib_logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, _HANDLER_MARK, False):
            root.removeHandler(existing)


def get_logger(service: str) -> structlog.stdlib.BoundLogger:
    """Devolve um logger com ``service`` associado."""
    return structlog.stdlib.get_logger().bind(service=service)


__all__ = [
    "ALLOWED_KEYS",
    "INVALID_EVENT_NAME",
    "build_shared_processors",
    "configure_logging",
    "content_free_filter",
    "get_logger",
    "make_safe_exc_info",
    "reset_logging_handlers",
]
