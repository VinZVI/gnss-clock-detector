"""
FTP-клиент для ftp.glonass-iac.ru/MCC/PRODUCTS/.

Структура сервера:
  /MCC/PRODUCTS/
    26079/            ← каталог = YYYYDDD (год 2026, DOY 079 = 20 марта)
      ultra/
        Stark_26032000.clk    ← RINEX CLK, слот 00h UTC  ~500 KB
        Stark_26032006.clk    ← слот 06h UTC
        Stark_26032000.sp3    ← SP3 ultra-rapid           ~80 KB
        Stark_1D_26032000.sp3 ← SP3 1-day                ~326 KB
        ...

Алгоритм:
  1. Строим список (date, slot_h) за N дней.
  2. Для каждого слота формируем каталог (YYYYDDD) и кандидатов по приоритету.
  3. Сравниваем с листингом FTP — скачиваем первый найденный.
  4. Уже загруженные файлы (из EtlLog) пропускаем без скачивания.
"""

from __future__ import annotations
import ftplib
import gzip
import io
import logging
from typing import Iterator, List, Optional, Tuple

from . import config
from .gps_time import date_to_dir, file_stem, slots_to_fetch
from .utils import decompress as _decompress

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FTP helpers
# ---------------------------------------------------------------------------

def _list_dir(ftp: ftplib.FTP, path: str) -> list[str]:
    """NLST каталога. Возвращает [] если каталог не существует."""
    try:
        ftp.cwd(path)
    except ftplib.error_perm as exc:
        logger.debug("FTP cwd %s: %s", path, exc)
        return []
    names: list[str] = []
    ftp.retrlines("NLST", names.append)
    return names


def _download(ftp: ftplib.FTP, name: str) -> Optional[bytes]:
    buf = io.BytesIO()
    try:
        ftp.retrbinary(f"RETR {name}", buf.write)
        raw = buf.getvalue()
        logger.info("  ↓ %s  (%s байт)", name, f"{len(raw):,}")
        return raw
    except ftplib.all_errors as exc:
        logger.error("  RETR %s: %s", name, exc)
        return None


# ---------------------------------------------------------------------------
# Кандидаты по приоритету для одного слота
# ---------------------------------------------------------------------------

def _candidates(dt, slot_h: int) -> List[Tuple[str, Optional[str]]]:
    """
    Кандидаты для ultra: Stark_YYMMDDHR.clk / .sp3 / 1D.sp3
    """
    prefix = config.PRODUCT_PREFIX
    candidates = []
    for tpl, ext, compression in config.FILE_PRIORITY:
        long_sp3 = "1D" in tpl
        stem = file_stem(prefix, dt, slot_h, long_sp3=long_sp3)
        fname = stem + ext + (compression or "")
        candidates.append((fname, compression))
    return candidates


def _candidates_daily(dt, prefix: str) -> List[Tuple[str, Optional[str]]]:
    """
    Кандидаты для rapid/final: один файл в сутки.
    На FTP final/rapid папки используют формат GPS-недели! (StaWWWW D.clk)
    Пример: Sta24105.clk (Неделя 2410, День 5)
    Также оставляем старый формат на случай, если он где-то используется.
    """
    from .gps_time import utc_to_gps_week

    yy  = dt.year % 100
    doy = dt.timetuple().tm_yday
    stem_doy = f"{prefix}{yy:02d}{doy:03d}"

    week, dow = utc_to_gps_week(dt)
    stem_gps = f"{prefix}{week:04d}{dow}"

    cands = []
    for stem in [stem_gps, stem_doy]:
        cands.extend([
            (stem + ".clk", None),
            (stem + ".clk.Z", ".Z"),
            (stem + ".sp3", None),
            (stem + ".sp3.Z", ".Z"),
        ])
    return cands


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def iter_new_files(
    days_back: int = config.ETL_DAYS_BACK,
    already_loaded: set[str] | None = None,
) -> Iterator[tuple[str, str, str]]:
    """
    Подключается к FTP, итерирует слоты за days_back дней (от новых к старым).
    Для каждого слота проверяет поддиректории в порядке приоритета:
        final (появляется через ~4 дня) → rapid → ultra
    Возвращает (filename, text_content) первого найденного файла.
    Файлы из already_loaded пропускаются без скачивания.
    """
    if already_loaded is None:
        already_loaded = set()

    # Приоритет: final лучше всего, потом rapid, потом ultra
    SUBDIRS = ["final", "rapid", "ultra"]

    slots = slots_to_fetch(days_back)
    logger.info("FTP: %d слотов за %d дней", len(slots), days_back)

    try:
        with ftplib.FTP() as ftp:
            ftp.connect(config.FTP_HOST, config.FTP_PORT, timeout=config.FTP_TIMEOUT)
            ftp.login(config.FTP_USER, config.FTP_PASSWD)
            ftp.set_pasv(True)
            logger.info("FTP: соединение %s", config.FTP_HOST)

            # Кэш листингов: path -> list[str]
            _dir_cache: dict[str, list[str]] = {}

            for dt, slot_h in slots:
                dir_tag = date_to_dir(dt)
                
                for subdir in SUBDIRS:
                    
                    ftp_path = f"{config.FTP_BASE}/{dir_tag}/{subdir}"

                    if ftp_path not in _dir_cache:
                        _dir_cache[ftp_path] = _list_dir(ftp, ftp_path)
                        logger.info("FTP ls %s → %d файлов", ftp_path, len(_dir_cache[ftp_path]))

                    names = _dir_cache[ftp_path]
                    if not names:
                        continue

                    server_set = set(names)
                    current_candidates = []

                    # 1. Суточные (Daily)
                    for p in ["Sta", "IPG", "IAU", "IAC"]:
                        current_candidates.extend(_candidates_daily(dt, p))

                    # 2. 6-часовые слоты (теперь ищем везде, не только в ultra)
                    current_candidates.extend(_candidates(dt, slot_h))

                    # 3. Высокоточные 30с (только в final)
                    if subdir == "final":
                        from .gps_time import utc_to_gps_week
                        week, dow = utc_to_gps_week(dt)
                        current_candidates.append((f"Sta30s{week:04d}{dow}.clk", None))

                    for fname, compression in current_candidates:
                        key = f"{subdir}/{fname}"
                        if key in already_loaded:
                            logger.debug("  пропуск (уже загружен): %s", key)
                            break

                        if fname not in server_set:
                            continue

                        raw = _download(ftp, fname)
                        if raw is None:
                            continue

                        text = _decompress(raw, fname)
                        if text is None:
                            continue

                        yield fname, text, subdir
                        break

    except ftplib.all_errors as exc:
        logger.error("FTP ошибка: %s", exc)
