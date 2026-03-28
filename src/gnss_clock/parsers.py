"""
Парсеры форматов SP3-c и RINEX Clock.

Оба возвращают list[dict]:
    {
        "sat_id":     str,      # "R01", "G05", "E11" …
        "epoch":      datetime,
        "clock_bias": float,    # наносекунды
    }
"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

_NO_DATA_THRESHOLD = 999990.0   # значение в SP3, означающее «нет данных»


# ---------------------------------------------------------------------------
# SP3-c
# ---------------------------------------------------------------------------

def parse_sp3(content: str, source: str = "glonass-iac") -> List[Dict[str, Any]]:
    """
    Парсит SP3-c файл.

    Строки эпохи:  * YYYY MM DD HH MM SS.SSSSSSS
    Строки данных: P<sat_id>  X  Y  Z  clk_us  [дополнительные поля]

    clock в SP3 — микросекунды (мкс); 999999.999999 = нет данных.
    Возвращаем в наносекундах (нс = мкс × 1000).
    """
    records: List[Dict[str, Any]] = []
    epoch: Optional[datetime] = None

    for line in content.splitlines():
        # Строка эпохи
        if line.startswith("*"):
            parts = line.split()
            if len(parts) >= 7:
                try:
                    epoch = datetime(
                        int(parts[1]), int(parts[2]), int(parts[3]),
                        int(parts[4]), int(parts[5]),
                        int(float(parts[6])),
                    )
                except ValueError:
                    epoch = None
            continue

        # Строка позиции + часов
        if line.startswith("P") and epoch is not None and len(line) > 60:
            sat_id = line[1:4].strip()
            if not sat_id:
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            try:
                clk_us = float(parts[4])
            except ValueError:
                continue
            if abs(clk_us) > _NO_DATA_THRESHOLD:
                continue

            records.append({
                "sat_id":     sat_id,
                "epoch":      epoch,
                "clock_bias": clk_us * 1_000.0,   # мкс → нс
                "source":     source,
            })

    logger.info("  SP3: %d записей", len(records))
    return records


# ---------------------------------------------------------------------------
# RINEX Clock (*.clk, *.cls, *.clu)
# ---------------------------------------------------------------------------

def _fortran_float(s: str) -> float:
    """
    Парсит число в Fortran D-нотации (и обычной E-нотации).
    '0.315054445281D-03' → 3.15054445281e-04
    Также убирает \r на случай Windows line endings.
    """
    return float(s.strip().upper().replace("D", "E"))


def parse_rinex_clk(content: str, source: str = "glonass-iac") -> List[Dict[str, Any]]:
    """
    Парсит RINEX Clock файл (версия 2.x и 3.x).

    Строки данных после END OF HEADER:
        AS  sat_id  YYYY MM DD HH MM SS.SSSSSSS  n_val  clk_s  [clk_rate_s]

    Особенности реальных файлов GLONASS-IAC:
      - Числа в Fortran D-нотации: 0.315054445281D-03  (не E!)
      - Возможны Windows CRLF (\r\n)
      - Секунды эпохи записаны как float с дробью: "0.000000"

    clock_bias в секундах → нс (* 1e9).
    Берём только строки AS (Satellite Clock); AR (station) игнорируем.
    """
    records: List[Dict[str, Any]] = []
    in_data = False

    for raw_line in content.splitlines():
        line = raw_line.rstrip()          # убираем \r и пробелы справа

        if "END OF HEADER" in line:
            in_data = True
            continue
        if not in_data:
            continue
        if not line.startswith("AS "):   # только спутниковые записи
            continue

        parts = line.split()
        # Формат: AS sat_id YYYY MM DD HH MM SS.S n clk_s [clk_rate]
        #          0   1     2    3  4  5  6   7   8   9      10
        if len(parts) < 10:
            continue

        try:
            sat_id = parts[1]
            epoch = datetime(
                int(parts[2]), int(parts[3]), int(parts[4]),
                int(parts[5]), int(parts[6]),
                int(float(parts[7])),
            )
            clk_s  = _fortran_float(parts[9])   # D-нотация → float
            clk_ns = clk_s * 1e9                # с → нс
        except (ValueError, IndexError):
            continue

        records.append({
            "sat_id":     sat_id,
            "epoch":      epoch,
            "clock_bias": clk_ns,
            "source":     source,
        })

    logger.info("  RINEX CLK: %d записей", len(records))
    return records


# ---------------------------------------------------------------------------
# Диспетчер
# ---------------------------------------------------------------------------

def parse_file(content: str, filename: str) -> list[dict]:
    """Определяет формат по имени файла и вызывает нужный парсер."""
    base = filename.lower()
    # убираем суффиксы сжатия
    for suf in (".z", ".gz"):
        if base.endswith(suf):
            base = base[: -len(suf)]
            break

    if any(base.endswith(x) for x in (".clk", ".cls", ".clu", ".clk_30s")):
        return parse_rinex_clk(content)
    if base.endswith(".sp3"):
        return parse_sp3(content)

    logger.warning("Неизвестный тип файла: %s", filename)
    return []
