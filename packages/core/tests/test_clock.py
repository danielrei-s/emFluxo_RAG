"""Testes de ``rag_core.clock``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from rag_core.clock import FakeClock, SystemClock


def test_system_clock_returns_utc_aware_now() -> None:
    now = SystemClock().now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_fake_clock_is_timezone_aware_and_advances() -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    assert clock.now().tzinfo is not None
    clock.advance(90)
    assert clock.now() == datetime(2026, 1, 1, 0, 1, 30, tzinfo=UTC)


def test_fake_clock_default_start_is_fixed() -> None:
    assert FakeClock().now() == FakeClock().now()


def test_fake_clock_set_replaces_time() -> None:
    clock = FakeClock()
    clock.set(datetime(2030, 5, 5, tzinfo=UTC))
    assert clock.now() == datetime(2030, 5, 5, tzinfo=UTC)


def test_fake_clock_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone"):
        FakeClock(datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="timezone"):
        FakeClock().set(datetime(2026, 1, 1))
