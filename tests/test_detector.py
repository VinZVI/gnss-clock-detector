"""Тесты MAD-детектора."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime, timedelta
from gnss_clock.detector import detect_outliers


def _make_ts(biases):
    base = datetime(2026, 3, 20, 0, 0, 0)
    return [
        {"epoch": base + timedelta(minutes=5*i), "clock_bias": b}
        for i, b in enumerate(biases)
    ]


def test_no_outliers():
    ts = _make_ts([100.0, 101.0, 99.5, 100.5, 100.2])
    results = detect_outliers(ts)
    assert not any(r.is_outlier for r in results)


def test_clear_outlier():
    biases = [100.0] * 10 + [5000.0]   # явный выброс
    ts = _make_ts(biases)
    results = detect_outliers(ts)
    assert results[-1].is_outlier


def test_delta_clock_first_is_none():
    ts = _make_ts([100.0, 101.0, 102.0])
    results = detect_outliers(ts)
    assert results[0].delta_clock is None


def test_short_series():
    ts = _make_ts([100.0, 101.0])   # < 3 точки
    results = detect_outliers(ts)
    assert not any(r.is_outlier for r in results)
    assert len(results) == 2


def test_empty():
    assert detect_outliers([]) == []
