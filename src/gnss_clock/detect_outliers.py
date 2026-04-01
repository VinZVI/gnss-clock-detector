"""
MAD-детектор выбросов часов спутников.

Алгоритм:
  1. Сортируем ряд по времени.
  2. Вычисляем delta_clock = d(bias)/dt (нс/с).
  3. Считаем median и MAD по ИЗМЕНЕНИЯМ (delta_clock), а не по самим значениям.
  4. Точка — аномалия, если ее delta_clock отклоняется от типичной скорости больше чем на threshold.
"""

from __future__ import annotations
import numpy as np
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class DetectionResult:
    epoch:       datetime
    clock_bias:  float
    delta_clock: Optional[float]
    is_outlier:  bool
    score:       float      # |delta - median| / MAD
    median:      float      # Теперь это медиана дельт (скоростей)
    mad:         float      # Теперь это MAD дельт


def detect_outliers(
    timeseries: list[dict],   # [{epoch: datetime, clock_bias: float}, ...]
    threshold: float = 3.0,
) -> list[DetectionResult]:
    """
    timeseries — список dict с ключами epoch и clock_bias.
    Возвращает список DetectionResult в хронологическом порядке.
    """
    if not timeseries:
        return []

    data = sorted(timeseries, key=lambda x: x["epoch"])
    n = len(data)

    if n < 3:
        return [
            DetectionResult(
                epoch=p["epoch"],
                clock_bias=p["clock_bias"],
                delta_clock=None,
                is_outlier=False,
                score=0.0,
                median=0.0,
                mad=0.0,
            )
            for p in data
        ]

    # 1. Вычисляем delta_clock (как у тебя и было)
    deltas: list[float | None] = [None]
    for i in range(1, n):
        dt = (data[i]["epoch"] - data[i - 1]["epoch"]).total_seconds()
        if dt > 0:
            deltas.append((data[i]["clock_bias"] - data[i - 1]["clock_bias"]) / dt)
        else:
            deltas.append(0.0)

    # 2. Считаем median и MAD исключительно по delta_clock!
    # Игнорируем первый None
    valid_deltas = np.array([d for d in deltas if d is not None], dtype=np.float64)
    
    median_delta = float(np.median(valid_deltas))
    abs_dev = np.abs(valid_deltas - median_delta)
    mad_delta = float(np.median(abs_dev)) or 1e-9   # Защита от деления на ноль

    # 3. Оцениваем каждую точку
    results = []
    for i, point in enumerate(data):
        delta = deltas[i]
        
        # Для первой точки у нас нет дельты, считаем ее нормальной
        if delta is None:
            score = 0.0
            is_outlier = False
        else:
            # Считаем, насколько скорость в этой точке нетипична
            score = float(abs(delta - median_delta) / mad_delta)
            is_outlier = score > threshold

        results.append(DetectionResult(
            epoch       = point["epoch"],
            clock_bias  = point["clock_bias"],
            delta_clock = delta,
            is_outlier  = is_outlier,
            score       = round(score, 4),
            median      = round(median_delta, 6),
            mad         = round(mad_delta, 6),
        ))

    return results