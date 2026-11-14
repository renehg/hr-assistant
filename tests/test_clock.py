"""Pruebas del reloj inyectado (``app/clock.py``)."""

from datetime import datetime, timedelta, timezone

from app.clock import FixedClock, SystemClock


def test_fixed_clock_repeats_its_moment_and_system_clock_is_utc():
    moment = datetime(2026, 3, 1, 8, 0, 0, tzinfo=timezone.utc)
    fixed = FixedClock(moment)
    assert fixed.now() == moment
    assert fixed.now() == moment

    system = SystemClock()
    assert system.now().utcoffset() == timedelta(0)
    first = system.monotonic()
    assert system.monotonic() >= first
