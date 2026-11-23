"""Testes de F11-T06: debounce e vigia real de pastas."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from rag_core.clock import FakeClock
from rag_local.events import EventBus, sse
from rag_local.watcher import Debouncer, WorkspaceWatcher, pump


def test_debounce_coalesces_events() -> None:
    clock = FakeClock(datetime(2026, 5, 10, tzinfo=UTC))
    debouncer = Debouncer(clock, delay_s=2.0)
    for _ in range(5):  # uma tempestade de eventos do mesmo caminho
        debouncer.add("/docs/a.txt")
        clock.advance(0.5)
    assert debouncer.due() == []  # o último evento foi há 0,5 s
    debouncer.add("/docs/b.txt")
    clock.advance(1.5)
    assert debouncer.due() == ["/docs/a.txt"]  # só o a.txt já passou os 2 s
    clock.advance(0.5)
    assert debouncer.due() == ["/docs/b.txt"]
    assert debouncer.due() == []  # cada caminho sai uma única vez


def test_pump_delivers_ready_paths() -> None:
    clock = FakeClock(datetime(2026, 5, 10, tzinfo=UTC))
    debouncer = Debouncer(clock)
    delivered: list[list[str]] = []
    assert pump(debouncer, delivered.append) == 0
    debouncer.add("x")
    clock.advance(3)
    assert pump(debouncer, delivered.append) == 1 and delivered == [["x"]]


def test_event_bus_carries_only_counts() -> None:
    bus = EventBus(maxlen=2)
    bus.publish("rescan", pending=3)
    bus.publish("indexed", count=1)
    bus.publish("deleted", count=2)  # o mais antigo cai
    events = bus.drain()
    assert events == [{"type": "indexed", "count": 1}, {"type": "deleted", "count": 2}]
    assert bus.drain() == []
    assert sse(events).startswith('data: {"type": "indexed"')


@pytest.mark.slow
def test_real_watchdog_detects_new_file(tmp_path: Path) -> None:
    class Wall:
        def now(self) -> datetime:
            return datetime.now(UTC)

    debouncer = Debouncer(Wall(), delay_s=0.2)
    watcher = WorkspaceWatcher(str(tmp_path), debouncer)
    watcher.start()
    try:
        time.sleep(0.3)
        (tmp_path / "novo.txt").write_text("olá", encoding="utf-8")
        found: list[str] = []
        deadline = time.time() + 5
        while time.time() < deadline and not any(p.endswith("novo.txt") for p in found):
            found += debouncer.due()
            time.sleep(0.1)
        assert any(p.endswith("novo.txt") for p in found)
    finally:
        watcher.stop()
