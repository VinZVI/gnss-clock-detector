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

def calculate_orbit_correlation(
    clock_results: List['DetectionResult'],
    orbit_history: List[Dict]
) -> Dict:
    """
    Рассчитывает корреляцию между аномалиями часов и орбитальными параметрами.
    """
    if not clock_results or not orbit_history:
        return {}

    # 1. Синхронизируем данные по времени
    # Для каждой точки часов ищем ближайшую точку орбиты
    matched = []
    orbit_epochs = np.array([datetime.fromisoformat(o['epoch']).timestamp() for o in orbit_history])
    
    for c in clock_results:
        c_ts = c.epoch.timestamp()
        idx = np.argmin(np.abs(orbit_epochs - c_ts))
        if np.abs(orbit_epochs[idx] - c_ts) < 3600: # порог 1 час
            matched.append({
                "is_outlier": c.is_outlier,
                "score": c.score,
                "residual": abs(c.clock_bias - c.median) if c.median is not None else 0,
                "mean_anomaly": orbit_history[idx]['mean_anomaly'],
                "altitude": orbit_history[idx]['a'] - 6371.0
            })
            
    if len(matched) < 10:
        return {}

    # 2. Статистический анализ
    anomalies = [m for m in matched if m['is_outlier']]
    
    # Распределение аномалий по орбите (M)
    m_bins = np.linspace(0, 360, 13)
    counts, _ = np.histogram([a['mean_anomaly'] for a in anomalies], bins=m_bins)
    
    # Корреляция Пирсона между высотой и шумом часов
    altitudes = np.array([m['altitude'] for m in matched])
    residuals = np.array([m['residual'] for m in matched])
    
    correlation_coeff = 0
    if np.std(altitudes) > 0 and np.std(residuals) > 0:
        correlation_coeff = np.corrcoef(altitudes, residuals)[0, 1]

    return {
        "anomaly_distribution": counts.tolist(),
        "height_clock_correlation": round(float(correlation_coeff), 3),
        "avg_altitude": round(float(np.mean(altitudes)), 1)
    }

