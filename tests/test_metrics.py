"""Pruebas de las métricas del proceso (``app/metrics.py``)."""

import os

import pytest

from app.metrics import Metrics, nearest_rank


def test_percentiles_use_the_nearest_rank():
    metrics = Metrics(slo_p95_ms=2000)
    for latency in range(1, 101):
        metrics.record_request(status=200, latency_ms=float(latency))

    snapshot = metrics.snapshot()

    assert snapshot["pid"] == os.getpid()
    assert snapshot["requests"] == 100
    assert snapshot["latency_ms"] == {"p50": 50, "p95": 95}
    assert snapshot["slo"] == {"p95_ms_target": 2000, "met": True}


def test_empty_metrics_report_zero_and_a_met_slo():
    snapshot = Metrics(slo_p95_ms=2000).snapshot()
    assert snapshot["requests"] == 0
    assert snapshot["error_rate"] == 0
    assert snapshot["latency_ms"] == {"p50": 0, "p95": 0}
    assert snapshot["tokens"] == {"input": 0, "output": 0}
    assert snapshot["slo"]["met"] is True


def test_error_rate_counts_only_server_errors():
    metrics = Metrics(slo_p95_ms=2000)
    for status in (200, 422, 500, 503):
        metrics.record_request(status=status, latency_ms=10.0)
    assert metrics.snapshot()["error_rate"] == 0.5


def test_latency_window_keeps_only_recent_requests_but_counts_all():
    metrics = Metrics(slo_p95_ms=2000, window=3)
    for latency in (5000.0, 10.0, 10.0, 10.0):
        metrics.record_request(status=200, latency_ms=latency)
    snapshot = metrics.snapshot()
    assert snapshot["requests"] == 4
    assert snapshot["latency_ms"]["p95"] == 10


def test_nearest_rank_handles_empty_single_and_many_values():
    assert nearest_rank([], 95) == 0
    assert nearest_rank([7.0], 50) == 7.0
    assert nearest_rank([7.0], 95) == 7.0
    assert nearest_rank([1.0, 2.0, 3.0, 4.0], 50) == 2.0
    assert nearest_rank([1.0, 2.0, 3.0, 4.0], 95) == 4.0


def test_slo_is_missed_when_p95_equals_the_target():
    metrics = Metrics(slo_p95_ms=2000)
    metrics.record_request(status=200, latency_ms=2000.0)
    assert metrics.snapshot()["slo"] == {"p95_ms_target": 2000, "met": False}


def test_tokens_are_summed_across_runs():
    metrics = Metrics(slo_p95_ms=2000)
    metrics.record_tokens(input_tokens=10, output_tokens=3)
    metrics.record_tokens(input_tokens=5, output_tokens=2)
    assert metrics.snapshot()["tokens"] == {"input": 15, "output": 5}


def test_cost_is_summed_across_runs_and_starts_at_zero():
    metrics = Metrics(slo_p95_ms=2000)
    assert metrics.snapshot()["cost_usd"] == 0
    metrics.record_cost(0.000012)
    metrics.record_cost(0.0000005)
    assert metrics.snapshot()["cost_usd"] == pytest.approx(0.0000125)


def test_latency_window_must_hold_at_least_one_value():
    with pytest.raises(ValueError, match="window"):
        Metrics(slo_p95_ms=2000, window=0)
