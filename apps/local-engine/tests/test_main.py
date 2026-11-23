"""Testes de F11-T01: arranque real do servidor local (handshake, loopback, processo pai)."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.enable_socket


def _start(
    tmp_path: Path, parent_pid: int, *extra: str
) -> tuple[subprocess.Popen[str], dict[str, Any]]:
    process = subprocess.Popen(
        [sys.executable, "-m", "rag_local.main", "serve", "--data-dir", str(tmp_path / "dados"),
         "--port", "0", "--parent-pid", str(parent_pid), *extra],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )  # fmt: skip
    assert process.stdout is not None
    line = process.stdout.readline()
    return process, json.loads(line)


@pytest.fixture
def parent() -> Iterator[subprocess.Popen[bytes]]:
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    yield process
    process.kill()
    process.wait()


def test_handshake_line_parsable_and_server_answers(tmp_path: Path, parent: Any) -> None:
    process, ready = _start(tmp_path, parent.pid)
    try:
        assert set(ready) == {"event", "port", "token", "version"} and ready["event"] == "ready"
        assert ready["port"] > 0 and len(ready["token"]) >= 40
        base = f"http://127.0.0.1:{ready['port']}"
        health = httpx.get(
            f"{base}/v1/health", headers={"Authorization": f"Bearer {ready['token']}"}
        )
        assert health.status_code == 200 and health.json()["version"] == ready["version"]
        assert httpx.get(f"{base}/v1/health").status_code == 401
        assert (tmp_path / "dados").is_dir()
    finally:
        process.kill()
        process.wait()


def test_inv11_binds_only_loopback(tmp_path: Path, parent: Any) -> None:
    process, ready = _start(tmp_path, parent.pid)
    try:
        with socket.create_connection(("127.0.0.1", ready["port"]), timeout=5):
            pass  # em loopback aceita
        lan_ip = socket.gethostbyname(socket.gethostname())
        if lan_ip.startswith("127."):
            pytest.skip("a máquina não tem outro endereço IPv4 para testar")
        with pytest.raises(OSError):  # no endereço de rede da máquina ninguém atende
            socket.create_connection((lan_ip, ready["port"]), timeout=3)
    finally:
        process.kill()
        process.wait()


def test_exits_when_parent_dies(tmp_path: Path, parent: Any) -> None:
    process, _ = _start(tmp_path, parent.pid)
    parent.kill()
    parent.wait()
    deadline = time.time() + 15
    while process.poll() is None and time.time() < deadline:
        time.sleep(0.2)
    assert process.poll() is not None, "o motor devia terminar quando o processo pai morre"


def test_inv13_token_not_in_logs(tmp_path: Path, parent: Any) -> None:
    process, ready = _start(tmp_path, parent.pid)
    base = f"http://127.0.0.1:{ready['port']}"
    headers = {"Authorization": f"Bearer {ready['token']}"}
    try:
        httpx.get(f"{base}/v1/health", headers=headers)
        httpx.get(f"{base}/v1/health", headers={"Authorization": "Bearer errado"})
    finally:
        process.kill()
        stdout_rest, stderr = process.communicate(timeout=10)
    assert ready["token"] not in stdout_rest and ready["token"] not in stderr
    assert "GET /v1/health" not in stderr  # sem logs de acesso
