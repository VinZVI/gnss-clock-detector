"""Модуль аналитики временных рядов часов спутников."""
import numpy as np
import allantools
from datetime import datetime
from typing import List, Dict, Optional

# Forward declaration for type hinting
if False:
    from .detector import DetectionResult

def calculate_satellite_analytics(
    detection_results: List['DetectionResult'],
    expected_interval_sec: int = 300 # Интервал для RINEX CLK ~5 минут
) -> Dict:
    """
    Рассчитывает аналитику на основе очищенных от выбросов данных.
    """
    # 1. Берем только "здоровые" точки для расчетов
    clean_data = [p for p in detection_results if not p.is_outlier]

    if len(clean_data) < 2:
        return {
            "avg_drift": 0, "max_jump": 0,
            "health_idx": 0, "noise_rms": 0,
            "allan_variance": None
        }

    # Временные метки и значения
    times = np.array([p.epoch.timestamp() for p in clean_data])
    biases = np.array([p.clock_bias for p in clean_data])

    # --- Средний дрейф (нс/с) ---
    total_time = times[-1] - times[0]
    if total_time > 0:
        drift = (biases[-1] - biases[0]) / total_time
    else:
        drift = 0

    # --- Максимальный скачок (нс) --- считается только по чистым точкам
    jumps = np.abs(np.diff(biases))
    max_jump = float(jumps.max()) if len(jumps) > 0 else 0

    # --- Индекс здоровья (%) ---
    actual_points = len(clean_data)
    expected_points = total_time / expected_interval_sec if total_time > 0 else 1
    health_idx = min(1.0, (actual_points / max(expected_points, len(detection_results))))

    # --- Шум (RMS) в нс ---
    if hasattr(clean_data[0], 'median') and clean_data[0].median is not None:
        residuals = np.array([p.clock_bias - p.median for p in clean_data])
    else:
        # Fallback if median is not available
        residuals = biases - np.mean(biases)

    rms = float(np.sqrt(np.mean(residuals**2)))

    # --- Allan Variance (ADEV) ---
    allan_variance = None
    if len(times) > 10:
        rate = 1.0 / expected_interval_sec
        # Интерполируем, чтобы заполнить пробелы для непрерывного временного ряда
        # для Allan Variance требуются равноотстоящие выборки
        t_interp = np.arange(times[0], times[-1], expected_interval_sec)
        if len(t_interp) > 10:
            b_interp = np.interp(t_interp, times, biases)

            # Конвертируем из нс в секунды для allantools (fractional frequency/phase)
            # В allantools фаза (x) передается в секундах
            phase_data = b_interp * 1e-9

            try:
                # Рассчитываем Overlapping Allan Deviation
                taus_out, adev, adeverr, ns = allantools.oadev(
                    data=phase_data,
                    rate=rate,
                    data_type="phase",
                    taus="decade"
                )
                allan_variance = {
                    "tau": taus_out.tolist(),
                    "adev": adev.tolist()
                }
            except Exception as e:
                print(f"Ошибка расчета Allan Variance: {e}")

    return {
        "avg_drift": round(drift, 6),
        "max_jump": round(max_jump, 3),
        "health_idx": round(health_idx, 3), # Изменим масштаб для UI, отдаем от 0 до 1 для совместимости с AnalyticsCache
        "noise_rms": round(rms, 4),
        "allan_variance": allan_variance
    }
