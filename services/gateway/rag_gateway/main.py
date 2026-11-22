"""Ponto de entrada (``uvicorn rag_gateway.main:app``); configuração e logging vêm do ambiente."""

from __future__ import annotations

from rag_core.config import get_settings
from rag_core.logging import configure_logging

from rag_gateway.app import create_app
from rag_gateway.wiring import build_deps

_settings = get_settings()
configure_logging("gateway", _settings.log_level, _settings.log_tracebacks)
app = create_app(_settings, build_deps(_settings))
