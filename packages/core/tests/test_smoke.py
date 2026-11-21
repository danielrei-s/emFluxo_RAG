"""Testes de fumo de F0-T02: pacote, marcadores e rede desligada."""

from __future__ import annotations

import re
import socket
import tomllib
from pathlib import Path

import pytest
import pytest_socket
import rag_core

ROOT = Path(__file__).resolve().parents[3]

C10_MARKERS = {
    "integration",
    "docker",
    "live",
    "slow",
    "docling",
    "ocr",
    "posix_only",
    "windows_only",
    "e2e",
}


def test_package_imports_and_has_version() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", rag_core.__version__)


def test_markers_registered() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ini = config["tool"]["pytest"]["ini_options"]
    registered = {m.split(":")[0].strip() for m in ini["markers"]}
    assert registered >= C10_MARKERS
    assert "--strict-markers" in ini["addopts"]


def test_network_is_disabled_in_unit_tests() -> None:
    with pytest.raises(pytest_socket.SocketBlockedError):
        socket.create_connection(("127.0.0.1", 9))
