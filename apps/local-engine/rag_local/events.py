"""Eventos para a UI (F11-T06): só contagens e estados, nunca nomes nem conteúdo."""

from __future__ import annotations

import json
import threading
from collections import deque
from typing import Any


class EventBus:
    """Fila em memória com os últimos eventos; ``/v1/events`` entrega-os em SSE."""

    def __init__(self, maxlen: int = 200) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def publish(self, kind: str, **counts: int) -> None:
        with self._lock:
            self._events.append({"type": kind, **counts})

    def drain(self) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._events)
            self._events.clear()
        return items


def sse(events: list[dict[str, Any]]) -> str:
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events)
