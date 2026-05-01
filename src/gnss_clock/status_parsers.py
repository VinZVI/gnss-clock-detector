"""
Парсеры статусных файлов ГЛОНАСС-ИАЦ.

  .glo — паспорта спутников (кодировка cp1251): тип КА, слот, плоскость, даты.
  .hlt — история состояний: периоды здоровья/обслуживания с кодом статуса.

Коды статуса .hlt:
  0 — Здоров
  1 — Не здоров
  3 — Техническое обслуживание
"""
import re
from datetime import datetime

def parse_date(date_str):
    """
    Парсит дату в формате DD.MM.YY
    Пример: 26.04.18 -> 2018-04-26
    Если год <= 50, считаем 2000+, иначе 1900+
    """
    try:
        parts = date_str.split('.')
        if len(parts) != 3:
            return None
        dd, mm, yy = int(parts[0]), int(parts[1]), int(parts[2])
        year = 2000 + yy if yy <= 50 else 1900 + yy
        return datetime(year, mm, dd).date()
    except:
        return None

def parse_datetime(date_str, time_str):
    """
    Парсит дату и время в формате DD.MM.YY HH:MM:SS
    """
    try:
        date_obj = parse_date(date_str)
        if not date_obj:
            return None
        time_parts = time_str.split(':')
        hr, mn, sc = int(time_parts[0]), int(time_parts[1]), int(time_parts[2])
        return datetime(date_obj.year, date_obj.month, date_obj.day, hr, mn, sc)
    except:
        return None

def parse_glo(content_str):
    """
    Разбирает файл .glo. На входе ожидаются байты, так как
    файл содержит кириллицу в кодировке cp1251.
    Возвращает список словарей.
    """
    text = content_str
    results = []

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        parts = re.split(r'\s+', line)
        if len(parts) >= 8:
            raw_id = parts[0]
            # Игнорируем строки-заголовки
            if raw_id.startswith(('#', '*')) or 'ID' in raw_id:
                continue

            slot = None
            try:
                # Извлекаем номер (например, R01 -> 1, или просто 1 -> 1)
                match = re.search(r'\d+', raw_id)
                if match:
                    slot = int(match.group())
            except:
                pass

            # Определяем систему и нормализуем sat_id
            if raw_id.startswith('G'):
                system = "GPS"
                sat_id = f"G{slot:02d}" if slot is not None else raw_id
            elif raw_id.startswith('R'):
                system = "GLONASS"
                sat_id = f"R{slot:02d}" if slot is not None else raw_id
            elif raw_id.startswith('E'):
                system = "Galileo"
                sat_id = f"E{slot:02d}" if slot is not None else raw_id
            elif raw_id.startswith('C'):
                system = "BeiDou"
                sat_id = f"C{slot:02d}" if slot is not None else raw_id
            elif raw_id.startswith('J'):
                system = "QZSS"
                sat_id = f"J{slot:02d}" if slot is not None else raw_id
            elif raw_id.startswith('I'):
                system = "NavIC"
                sat_id = f"I{slot:02d}" if slot is not None else raw_id
            elif raw_id.startswith('S'):
                system = "SBAS"
                sat_id = f"S{slot:02d}" if slot is not None else raw_id
            else:
                # Если просто число, по умолчанию GLONASS (специфика ГЛОНАСС-ИАЦ)
                if slot is not None:
                    system = "GLONASS"
                    sat_id = f"R{slot:02d}"
                else:
                    continue # Непонятный ID

            sat_type = parts[4] if len(parts) > 4 else "Unknown"
            assessment_date = parse_date(parts[5]) if len(parts) > 5 else None
            launch_date = parse_date(parts[6]) if len(parts) > 6 else None
            commission_date = parse_date(parts[7]) if len(parts) > 7 else None

            plane = None
            if slot and system == "GLONASS":
                if 1 <= slot <= 8: plane = 1
                elif 9 <= slot <= 16: plane = 2
                elif 17 <= slot <= 24: plane = 3

            results.append({
                "sat_id": sat_id,
                "slot": slot,
                "sat_num": parts[2] if len(parts) > 2 else None,
                "sat_type": sat_type,
                "assessment_date": assessment_date,
                "launch_date": launch_date,
                "commission_date": commission_date,
                "in_service_date": commission_date,
                "system": system,
                "plane": plane
            })

    return results

def parse_oe(content_str):
    """
    Разбирает файл .oe с орбитальными элементами.
    Формат строки: SatID Num Type Date Seconds a e Omega i omega M
    Пример: G01 80 0 26/01/01 0 26559.604 0.0013155 340.945886 54.907335 357.277480 127.907755
    """
    results = []
    for line in content_str.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = re.split(r'\s+', line)
        if len(parts) >= 11:
            try:
                sat_id = parts[0]
                # Извлекаем элементы: a (5), e (6), i (8)
                a = float(parts[5])
                e = float(parts[6])
                i = float(parts[8])
                
                results.append({
                    "sat_id": sat_id,
                    "orbit_a": a,
                    "orbit_e": e,
                    "orbit_i": i
                })
            except (ValueError, IndexError):
                continue
    return results

def parse_hlt(content_str):
    """
    Разбирает файл .hlt со статусами спутников.
    Формат: C01 DD.MM.YY HH:MM:SS DD.MM.YY HH:MM:SS  0
    """
    results = []

    for line in content_str.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        parts = re.split(r'\s+', line)
        if len(parts) >= 6:
            sat_id = parts[0]
            start_date, start_time = parts[1], parts[2]
            end_date, end_time = parts[3], parts[4]
            try:
                status_code = int(parts[5])
            except ValueError:
                continue

            start_epoch = parse_datetime(start_date, start_time)
            end_epoch = parse_datetime(end_date, end_time)

            if start_epoch and end_epoch:
                results.append({
                    "sat_id": sat_id,
                    "start_epoch": start_epoch,
                    "end_epoch": end_epoch,
                    "status_code": status_code,
                })

    return results
