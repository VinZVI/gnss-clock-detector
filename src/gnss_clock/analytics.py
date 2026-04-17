import numpy as np
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
            "health_idx": 0, "noise_rms": 0
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
    health_idx = min(100.0, (actual_points / max(expected_points, len(detection_results))) * 100)

    # --- Шум (RMS) в нс ---
    residuals = np.array([p.clock_bias - p.median for p in clean_data])
    rms = float(np.sqrt(np.mean(residuals**2)))

    return {
        "avg_drift": round(drift, 6),
        "max_jump": round(max_jump, 3),
        "health_idx": round(health_idx, 1),
        "noise_rms": round(rms, 4)
    }
