"""Middlewares do gateway: os comuns de ``rag_core.web`` (ver ``install_standard_web``)."""

from __future__ import annotations

from fastapi import FastAPI
from rag_core.web import install_standard_web

# 256 KB chega para pedidos de chat; excertos grandes vão no corpo, não em anexos.
MAX_BODY_BYTES = 256 * 1024


def install_middleware(app: FastAPI) -> None:
    install_standard_web(app, MAX_BODY_BYTES)
