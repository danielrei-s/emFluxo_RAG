"""Relógios: o real (UTC) e um falso e controlável para testes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

_DEFAULT_START = datetime(2026, 1, 1, tzinfo=UTC)


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime tem de ter timezone")
    return value


class SystemClock:
    """Relógio do sistema, sempre UTC e timezone-aware."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    """Relógio determinístico para testes; só avança quando mandado."""

    def __init__(self, start: datetime = _DEFAULT_START) -> None:
        self._now = _require_aware(start)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        """Avança o relógio ``seconds`` segundos."""
        self._now += timedelta(seconds=seconds)

    def set(self, dt: datetime) -> None:
        """Define o instante atual (tem de ser timezone-aware)."""
        self._now = _require_aware(dt)
