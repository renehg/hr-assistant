"""Pruebas del logger JSON (``app/logging_json.py``)."""

import io
import json
from datetime import datetime, timedelta, timezone

from app.clock import FixedClock
from app.logging_json import JsonLogger

MOMENT = datetime(2026, 1, 15, 12, 30, 0, tzinfo=timezone.utc)


def test_each_event_is_one_json_line_with_the_required_fields():
    stream = io.StringIO()
    logger = JsonLogger(service="hr-assistant", clock=FixedClock(MOMENT), stream=stream)

    logger.emit("request", "req-1", method="GET", path="/health", status=200)
    logger.emit("audit", "req-1", action="tool_call", tool="get_employee", args={})

    lines = stream.getvalue().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["event"] == "request"
    assert first["service"] == "hr-assistant"
    assert first["request_id"] == "req-1"
    assert first["status"] == 200
    timestamp = datetime.fromisoformat(first["ts"].replace("Z", "+00:00"))
    assert timestamp == MOMENT
    assert timestamp.utcoffset() == timedelta(0)
    assert json.loads(lines[1])["tool"] == "get_employee"


def test_a_malicious_value_cannot_break_the_line():
    stream = io.StringIO()
    logger = JsonLogger(service="hr-assistant", clock=FixedClock(MOMENT), stream=stream)

    logger.emit("request", 'evil\n{"event": "fake"}', path="/x")

    lines = stream.getvalue().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["request_id"] == 'evil\n{"event": "fake"}'


def test_event_fields_cannot_overwrite_the_required_fields():
    stream = io.StringIO()
    logger = JsonLogger(service="hr-assistant", clock=FixedClock(MOMENT), stream=stream)

    logger.emit("audit", "req-1", service="fake", ts="1999-01-01T00:00:00Z")

    record = json.loads(stream.getvalue())
    assert record["service"] == "hr-assistant"
    assert record["ts"].startswith("2026-01-15T12:30:00")
    assert record["event"] == "audit"


def test_timestamp_is_converted_to_utc_with_a_z_suffix():
    mexico_city = timezone(timedelta(hours=-6))
    local_moment = datetime(2026, 1, 15, 6, 30, 0, tzinfo=mexico_city)
    stream = io.StringIO()
    logger = JsonLogger(
        service="hr-assistant", clock=FixedClock(local_moment), stream=stream
    )

    logger.emit("request", "req-1")

    timestamp = json.loads(stream.getvalue())["ts"]
    assert timestamp.endswith("Z")
    assert timestamp.startswith("2026-01-15T12:30:00")


def test_logger_writes_to_standard_output_by_default(capsys):
    logger = JsonLogger(service="hr-assistant", clock=FixedClock(MOMENT))

    logger.emit("request", "req-stdout", status=200)

    record = json.loads(capsys.readouterr().out)
    assert record["request_id"] == "req-stdout"
    assert record["status"] == 200
