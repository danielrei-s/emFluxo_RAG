"""Fixture ``captured_logs``: devolve os eventos de log já processados pelo pipeline."""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any

import pytest
import structlog

from rag_core.logging import configure_logging, reset_logging_handlers


@pytest.fixture
def captured_logs() -> Iterator[list[dict[str, Any]]]:
    """Lista de eventos (dicts) emitidos via structlog ou logging da stdlib."""
    events: list[dict[str, Any]] = []
    configure_logging("test", "DEBUG", stream=io.StringIO(), sink=events.append)
    try:
        yield events
    finally:
        reset_logging_handlers()
        structlog.reset_defaults()
