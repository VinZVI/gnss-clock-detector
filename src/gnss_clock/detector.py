"""
MAD-детектор выбросов часов спутников.

Алгоритм:
  1. Сортируем ряд по времени.
  2. Вычисляем delta_clock = d(bias)/dt (нс/с).
  3. Считаем median и MAD по clock_bias всего ряда.
  4. Точка — аномалия, если |bias - median| / MAD > threshold.

Методы:
  - 'bias': классический MAD по значениям clock_bias (по умолчанию)
  - 'delta': новый MAD по изменениям delta_clock (скоростям)
"""

from __future__ import annotations
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class DetectionResult:
    epoch:       datetime
    clock_bias:  float
    delta_clock: Optional[float]
    is_outlier:  bool
    score:       float      # |x - median| / MAD
    median:      float
    mad:         float


def detect_outliers(
    timeseries: list[dict],   # [{epoch: datetime, clock_bias: float}, ...]
    threshold: float = 3.0,
    method: str = 'bias',     # 'bias' (classic) or 'delta' (new)
) -> list[DetectionResult]:
    """
    timeseries — список dict с ключами epoch и clock_bias.
    method — 'bias' (MAD по значениям) или 'delta' (MAD по скоростям изменений).
    threshold — порог в единицах MAD (рекомендуется 3.0).
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

    # Вычисляем delta_clock для всех точек
    deltas: list[float | None] = [None]
    for i in range(1, n):
        dt = (data[i]["epoch"] - data[i - 1]["epoch"]).total_seconds()
        if dt > 0:
            deltas.append((data[i]["clock_bias"] - data[i - 1]["clock_bias"]) / dt)
        else:
            deltas.append(0.0)

    # Выбираем метод детекции
    if method.lower() == 'delta':
        # Новый метод: MAD по изменениям (delta_clock)
        valid_deltas = np.array([d for d in deltas if d is not None], dtype=np.float64)
        median = float(np.median(valid_deltas))
        abs_dev = np.abs(valid_deltas - median)
        mad = float(np.median(abs_dev)) or 1e-9
        
        results = []
        for i, point in enumerate(data):
            delta = deltas[i]
            if delta is None:
                score = 0.0
                is_outlier = False
            else:
                score = float(abs(delta - median) / mad)
                is_outlier = score > threshold
            
            results.append(DetectionResult(
                epoch=point["epoch"],
                clock_bias=point["clock_bias"],
                delta_clock=delta,
                is_outlier=is_outlier,
                score=round(score, 4),
                median=round(median, 6),
                mad=round(mad, 6),
            ))
    else:
        # Классический метод: MAD по значениям (clock_bias)
        values  = np.array([p["clock_bias"] for p in data], dtype=np.float64)
        median  = float(np.median(values))
        abs_dev = np.abs(values - median)
        mad     = float(np.median(abs_dev)) or 1e-9
        
        results = []
        for i, point in enumerate(data):
            score      = float(abs_dev[i] / mad)
            results.append(DetectionResult(
                epoch       = point["epoch"],
                clock_bias  = point["clock_bias"],
                delta_clock = deltas[i],
                is_outlier  = score > threshold,
                score       = round(score, 4),
                median      = round(median, 6),
                mad         = round(mad, 6),
            ))

    return results
