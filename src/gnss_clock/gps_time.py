"""
Утилиты для работы со временем в контексте FTP GLONASS-IAC.

Структура каталогов на FTP:
  /MCC/PRODUCTS/<YYYYDDD>/ultra/
  где YYYYDDD = год(4 цифры) + день года (3 цифры, 001..366)
  Пример: 26079 → год 2026, DOY 079 → 20 марта 2026

Формат имён файлов внутри каталога:
  Stark_<YYMMDDHR>.<ext>
  где YY=год(2), MM=месяц(2), DD=день(2), HR=час UTC (2)
  Файлы выходят каждые 6 часов: слоты 00, 06, 12, 18 UTC.
  Пример: Stark_26032000.clk → 20 марта 2026, 00:00 UTC
"""

from datetime import datetime, timezone, timedelta

SLOT_HOURS = 6   # файлы выходят каждые 6 часов


# ---------------------------------------------------------------------------
# Каталог: YYYYDDD
# ---------------------------------------------------------------------------

def date_to_dir(dt: datetime) -> str:
    """
    Возвращает имя каталога на FTP для даты dt.

    datetime(2026, 3, 20) → '26079'
    """
    yy  = dt.year % 100
    doy = dt.timetuple().tm_yday
    return f"{yy:02d}{doy:03d}"


def dir_to_date(dir_name: str) -> datetime:
    """
    Разбирает имя каталога '26079' → datetime(2026, 3, 20).
    Предполагает 21-й век (2000+YY).
    """
    yy  = int(dir_name[:2])
    doy = int(dir_name[2:])
    return datetime(2000 + yy, 1, 1) + timedelta(days=doy - 1)


# ---------------------------------------------------------------------------
# Имя файла: YYMMDDHR
# ---------------------------------------------------------------------------

def slot_for(dt: datetime) -> int:
    """Ближайший прошедший 6-часовой слот: 0, 6, 12 или 18."""
    return (dt.hour // SLOT_HOURS) * SLOT_HOURS


def file_tag(dt: datetime, slot_h: int | None = None) -> str:
    """
    Возвращает YYMMDDHR-тег для имени файла.

    file_tag(datetime(2026, 3, 20),  0) → '26032000'
    file_tag(datetime(2026, 3, 20),  6) → '26032006'
    file_tag(datetime(2026, 3, 20), 12) → '26032012'
    """
    if slot_h is None:
        slot_h = slot_for(dt)
    yy = dt.year % 100
    return f"{yy:02d}{dt.month:02d}{dt.day:02d}{slot_h:02d}"


def file_stem(prefix: str, dt: datetime, slot_h: int, long_sp3: bool = False) -> str:
    """
    Полное имя без расширения.

    file_stem('Stark', datetime(2026,3,20), 0)       → 'Stark_26032000'
    file_stem('Stark', datetime(2026,3,20), 0, True)  → 'Stark_1D_26032000'
    """
    tag = file_tag(dt, slot_h)
    if long_sp3:
        return f"{prefix}_1D_{tag}"
    return f"{prefix}_{tag}"


# ---------------------------------------------------------------------------
# Список слотов для загрузки
# ---------------------------------------------------------------------------

def slots_to_fetch(days_back: int, now: datetime | None = None) -> list[tuple[datetime, int]]:
    """
    Возвращает список (date, slot_h) за последние days_back дней,
    от текущего слота к старым. Каждый элемент — уникальная пара дата+слот.

    slots_to_fetch(1, datetime(2026,3,20,10)) →
        [(datetime(2026,3,20), 6),
         (datetime(2026,3,20), 0),
         (datetime(2026,3,19), 18),
         (datetime(2026,3,19), 12)]
    """
    if now is None:
        now = datetime.now(timezone.utc)

    result = []
    total_slots = days_back * (24 // SLOT_HOURS)

    current_slot_dt = now.replace(
        hour=slot_for(now), minute=0, second=0, microsecond=0
    )

    for i in range(total_slots):
        t = current_slot_dt - timedelta(hours=i * SLOT_HOURS)
        date_only = t.replace(hour=0, minute=0, tzinfo=None)
        result.append((date_only, t.hour))

    return result


# ---------------------------------------------------------------------------
# GPS-неделя (для NASA CDDIS)
# ---------------------------------------------------------------------------
# NASA CDDIS использует GPS-неделю в именах файлов:
#   igu<WWWW><D>_<HH>.sp3.gz  (WWWW=неделя, D=день, HH=слот)
#   Например: igu26032_00.sp3.gz → неделя 2603, день 2 (вт), слот 00

_GPS_EPOCH = datetime(1980, 1, 6, tzinfo=timezone.utc)


def utc_to_gps_week(dt: datetime) -> tuple[int, int]:
    """
    Возвращает (gps_week, gps_day_of_week).
    gps_day_of_week: 0=воскресенье, 1=понедельник … 6=суббота.

    utc_to_gps_week(datetime(2026, 3, 20, tzinfo=UTC)) → (2603, 2)
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    total_days = (dt - _GPS_EPOCH).days
    return total_days // 7, total_days % 7


def nasa_file_stem(product: str, gps_week: int, gps_dow: int, slot_h: int) -> str:
    """
    Формирует основу имени файла NASA CDDIS.

    nasa_file_stem('igu', 2603, 2, 0) → 'igu26032_00'
    nasa_file_stem('igr', 2603, 2, 0) → 'igr26032'      (rapid — нет слота)
    nasa_file_stem('igs', 2603, 0, 0) → 'igs26030'      (final — нет слота)
    """
    base = f"{product}{gps_week:04d}{gps_dow}"
    if product == "igu":
        return f"{base}_{slot_h:02d}"
    return base


def nasa_slots_to_fetch(
    days_back: int,
    product: str = "igu",
    now: datetime | None = None,
) -> list[tuple[int, int, int]]:
    """
    Возвращает список (gps_week, gps_dow, slot_h) за последние days_back дней,
    от новейшего к старейшему.

    Для 'igu' (ultra-rapid): 4 слота в сутки (00, 06, 12, 18).
    Для 'igr' (rapid):       1 слот в сутки (slot_h всегда 0).
    Для 'igs' (final):       1 слот в сутки (slot_h всегда 0).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    result = []

    if product == "igu":
        # 4 слота × days_back
        total_slots = days_back * (24 // SLOT_HOURS)
        cur = now.replace(hour=slot_for(now), minute=0, second=0, microsecond=0)
        for i in range(total_slots):
            t = cur - timedelta(hours=i * SLOT_HOURS)
            w, d = utc_to_gps_week(t)
            result.append((w, d, t.hour))
    else:
        # 1 файл в сутки
        for i in range(days_back):
            t = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=i)
            w, d = utc_to_gps_week(t)
            result.append((w, d, 0))

    return result
