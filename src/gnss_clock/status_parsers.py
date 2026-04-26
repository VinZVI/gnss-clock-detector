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
    Парсит дату в формате YY.MM.DD
    Пример: 18.04.26 -> 2018-04-26
    Если год <= 50, считаем 2000+, иначе 1900+
    """
    try:
        parts = date_str.split('.')
        if len(parts) != 3:
            return None
        yy, mm, dd = int(parts[0]), int(parts[1]), int(parts[2])
        year = 2000 + yy if yy <= 50 else 1900 + yy
        return datetime(year, mm, dd).date()
    except:
        return None

def parse_datetime(date_str, time_str):
    """
    Парсит дату и время в формате YY.MM.DD HH:MM:SS
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
        if len(parts) >= 9:
            sat_id = parts[0]
            # Игнорируем строки, где нет нормального идентификатора спутника (например, G01, R01)
            if len(sat_id) < 3 or sat_id[0] not in ('R', 'G', 'E', 'C', 'J') or '-' in sat_id:
                # В .glo бывают строки-заголовки или пустые слоты (например "-4")
                continue

            slot = None
            try:
                slot = int(parts[1])
            except:
                pass

            sat_type = parts[4]
            # parts[5] - текущая дата, пропускаем
            launch_date = parse_date(parts[6])
            commission_date = parse_date(parts[7])

            system = "GLONASS"
            if sat_id.startswith('G'): system = "GPS"
            elif sat_id.startswith('E'): system = "Galileo"
            elif sat_id.startswith('C'): system = "BeiDou"

            plane = None
            if slot and system == "GLONASS":
                if 1 <= slot <= 8: plane = 1
                elif 9 <= slot <= 16: plane = 2
                elif 17 <= slot <= 24: plane = 3

            results.append({
                "sat_id": sat_id,
                "slot": slot,
                "sat_type": sat_type,
                "launch_date": launch_date,
                "commission_date": commission_date,
                "in_service_date": commission_date,  # Используем комиссию как ввод в сервис
                "system": system,
                "plane": plane
            })

    return results

def parse_hlt(content_str):
    """
    Разбирает файл .hlt со статусами спутников.
    Формат: C01 18.04.26 00:00:00 19.04.26 00:00:00  0
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
