"""``rag-local serve``: servidor só em loopback, com token e vigilância do processo pai (F11-T01).

Imprime **uma** linha JSON no stdout (``{"event":"ready","port":P,"token":T,"version":V}``) e
nunca mais escreve o token (INV-13): sem logs de acesso e sem eco do cabeçalho.
"""

from __future__ import annotations

import argparse
import json
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

import psutil
import uvicorn

from rag_local import __version__
from rag_local.app import create_app

WATCH_INTERVAL_S = 1.0


def bind_loopback(port: int = 0) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", port))
    sock.listen(64)
    return sock


def parent_alive(pid: int) -> bool:
    return bool(psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE)


def watch_parent(pid: int, server: uvicorn.Server, interval_s: float = WATCH_INTERVAL_S) -> None:
    """Termina o servidor quando o processo pai morre."""
    while not server.should_exit:
        if not parent_alive(pid):
            server.should_exit = True
            return
        time.sleep(interval_s)


def serve(data_dir: Path, port: int, parent_pid: int, dev: bool = False) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    sock = bind_loopback(port)
    real_port = sock.getsockname()[1]
    token = secrets.token_urlsafe(32)
    app = create_app(token=token, port=real_port, dev=dev)
    config = uvicorn.Config(app, log_config=None, access_log=False, lifespan="off")
    server = uvicorn.Server(config)
    threading.Thread(target=watch_parent, args=(parent_pid, server), daemon=True).start()
    ready = {"event": "ready", "port": real_port, "token": token, "version": __version__}
    sys.stdout.write(json.dumps(ready) + "\n")
    sys.stdout.flush()
    server.run(sockets=[sock])


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rag-local")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("serve", help="arranca o servidor local")
    run.add_argument("--data-dir", type=Path, required=True)
    run.add_argument("--port", type=int, default=0)
    run.add_argument("--parent-pid", type=int, required=True)
    run.add_argument("--dev", action="store_true", help="aceita também a origem do Vite")
    args = parser.parse_args(argv)
    serve(args.data_dir, args.port, args.parent_pid, args.dev)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
