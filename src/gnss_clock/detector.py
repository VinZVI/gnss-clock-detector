"""
MAD-детектор выбросов часов спутников со скользящим окном.

Алгоритм:
  1. Сортируем ряд по времени.
  2. Для каждой точки берем "окно" соседей (например, 7 до и 7 после).
  3. Считаем локальную медиану и локальный MAD внутри этого окна.
  4. Точка — аномалия, если отклоняется от своей локальной медианы больше чем на threshold.
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
    score:       float      
    median:      float      # Теперь это локальная медиана (в наносекундах)
    mad:         float      # Теперь это локальный MAD (в наносекундах)


def detect_outliers(
    timeseries: list[dict],   # [{epoch: datetime, clock_bias: float}, ...]
    threshold: float = 3.0,
    window_size: int = 15,    # Размер скользящего окна (сколько точек анализируем за раз)
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
                median=p["clock_bias"],
                mad=0.0,
            )
            for p in data
        ]

    # 1. Считаем delta_clock (оставляем для информации в интерфейсе)
    deltas: list[float | None] = [None]
    for i in range(1, n):
        dt = (data[i]["epoch"] - data[i - 1]["epoch"]).total_seconds()
        if dt > 0:
            deltas.append((data[i]["clock_bias"] - data[i - 1]["clock_bias"]) / dt)
        else:
            deltas.append(0.0)

    # Вытаскиваем все значения clock_bias в массив для быстрых расчетов
    biases = np.array([p["clock_bias"] for p in data], dtype=np.float64)
    
    # Половина окна (сколько точек брать слева и справа)
    half_window = window_size // 2

    results = []
    for i, point in enumerate(data):
        # 2. Определяем границы локального окна (с защитой от выхода за края)
        start_idx = max(0, i - half_window)
        end_idx   = min(n, i + half_window + 1)
        
        window_data = biases[start_idx:end_idx]
        
        # 3. Считаем локальную медиану и MAD для этого кусочка графика
        local_median = float(np.median(window_data))
        abs_dev = np.abs(window_data - local_median)
        local_mad = float(np.median(abs_dev)) or 1e-9  # Защита от деления на ноль
        
        # 4. Оцениваем, насколько текущая точка выбивается из своего окна
        score = float(abs(point["clock_bias"] - local_median) / local_mad)
        is_outlier = score > threshold

        results.append(DetectionResult(
            epoch       = point["epoch"],
            clock_bias  = point["clock_bias"],
            delta_clock = deltas[i],
            is_outlier  = is_outlier,
            score       = round(score, 4),
            median      = round(local_median, 6),
            mad         = round(local_mad, 6),
        ))

    return results
