"""Vigia das pastas com debounce (F11-T06): muitos eventos do mesmo caminho viram uma reanálise."""

from __future__ import annotations

import threading
from collections.abc import Callable

from rag_core.interfaces import Clock
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

DEBOUNCE_S = 2.0


class Debouncer:
    """Um caminho só fica pronto depois de ``delay_s`` sem novos eventos."""

    def __init__(self, clock: Clock, delay_s: float = DEBOUNCE_S) -> None:
        self._clock = clock
        self._delay = delay_s
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def add(self, path: str) -> None:
        with self._lock:
            self._last[path] = self._clock.now().timestamp()

    def due(self) -> list[str]:
        now = self._clock.now().timestamp()
        with self._lock:
            ready = sorted(p for p, t in self._last.items() if now - t >= self._delay)
            for path in ready:
                del self._last[path]
        return ready


class _Handler(FileSystemEventHandler):
    def __init__(self, debouncer: Debouncer) -> None:
        self._debouncer = debouncer

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type in {"opened", "closed_no_write"}:
            return  # leituras não são alterações
        self._debouncer.add(str(event.src_path))
        if event.dest_path:
            self._debouncer.add(str(event.dest_path))


class WorkspaceWatcher:
    """Um ``Observer`` do watchdog por raiz (recursivo)."""

    def __init__(self, root: str, debouncer: Debouncer) -> None:
        self._observer: BaseObserver = Observer()
        self._observer.schedule(_Handler(debouncer), root, recursive=True)

    def start(self) -> None:
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join(timeout=5)


def pump(debouncer: Debouncer, on_due: Callable[[list[str]], None]) -> int:
    """Entrega os caminhos prontos (a thread do motor chama isto periodicamente)."""
    ready = debouncer.due()
    if ready:
        on_due(ready)
    return len(ready)
