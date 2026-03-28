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

import ftplib
import gzip
import io
import logging
from typing import Iterator, Optional
from __future__ import annotations

from . import config
from .gps_time import date_to_dir, file_stem, slots_to_fetch

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Decompress
# ---------------------------------------------------------------------------

def _decompress(data: bytes, filename: str) -> Optional[str]:
    lo = filename.lower()

    if lo.endswith(".z"):
        try:
            import unlzw3
            return unlzw3.unlzw(data).decode("utf-8", errors="replace")
        except ImportError:
            logger.warning("unlzw3 не установлен, пробуем gzip-fallback для %s", filename)
        except Exception as exc:
            logger.warning("unlzw3 ошибка %s: %s, пробуем gzip-fallback", filename, exc)
        try:
            return gzip.decompress(data).decode("utf-8", errors="replace")
        except Exception:
            logger.error("Не удалось распаковать %s. pip install unlzw3", filename)
            return None

    if lo.endswith(".gz"):
        try:
            return gzip.decompress(data).decode("utf-8", errors="replace")
        except Exception as exc:
            logger.error("gzip ошибка %s: %s", filename, exc)
            return None

    # файл не сжат (как Stark_*.clk / *.sp3 на glonass-iac)
    return data.decode("utf-8", errors="replace")


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
    Возвращает [(имя_файла, суффикс_сжатия|None), ...] в порядке приоритета.

    Порядок (из config.FILE_PRIORITY):
        Stark_YYMMDDHR.clk          ← RINEX CLK без архива  ✓ приоритет
        Stark_YYMMDDHR.clk.Z        ← RINEX CLK сжатый
        Stark_YYMMDDHR.sp3          ← SP3 ultra
        Stark_YYMMDDHR.sp3.Z
        Stark_1D_YYMMDDHR.sp3       ← SP3 1-day
        Stark_1D_YYMMDDHR.sp3.Z
    """
    prefix = config.PRODUCT_PREFIX
    candidates = []
    for tpl, ext, compression in config.FILE_PRIORITY:
        long_sp3 = "1D" in tpl
        stem = file_stem(prefix, dt, slot_h, long_sp3=long_sp3)
        fname = stem + ext + (compression or "")
        candidates.append((fname, compression))
    return candidates


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def iter_new_files(
    days_back: int = config.ETL_DAYS_BACK,
    already_loaded: set[str] | None = None,
) -> Iterator[tuple[str, str]]:
    """
    Подключается к FTP, итерирует слоты за days_back дней (от новых к старым).
    Для каждого слота возвращает (filename, text_content) первого найденного файла.
    Файлы из already_loaded пропускаются без скачивания.
    """
    if already_loaded is None:
        already_loaded = set()

    slots = slots_to_fetch(days_back)
    logger.info("FTP: %d слотов за %d дней", len(slots), days_back)

    try:
        with ftplib.FTP() as ftp:
            ftp.connect(config.FTP_HOST, config.FTP_PORT, timeout=config.FTP_TIMEOUT)
            ftp.login(config.FTP_USER, config.FTP_PASSWD)
            ftp.set_pasv(True)
            logger.info("FTP: соединение %s", config.FTP_HOST)

            _cached_dir: tuple[str, list[str]] = ("", [])  # (path, names) кэш листинга

            for dt, slot_h in slots:
                # Каталог: /MCC/PRODUCTS/26079/ultra/
                dir_tag  = date_to_dir(dt)
                ftp_path = f"{config.FTP_BASE}/{dir_tag}/{config.FTP_SUBDIR}"

                # Получаем листинг (кэшируем для одного дня — 4 слота)
                if _cached_dir[0] != ftp_path:
                    names = _list_dir(ftp, ftp_path)
                    _cached_dir = (ftp_path, names)
                else:
                    names = _cached_dir[1]

                if not names:
                    continue

                server_set = set(names)

                for fname, compression in _candidates(dt, slot_h):
                    if fname in already_loaded:
                        logger.debug("  пропуск (уже загружен): %s", fname)
                        break  # файл этого слота уже в БД

                    if fname not in server_set:
                        continue

                    raw = _download(ftp, fname)
                    if raw is None:
                        continue

                    text = _decompress(raw, fname)
                    if text is None:
                        continue

                    yield fname, text
                    break   # нашли лучший файл для слота — переходим к следующему

    except ftplib.all_errors as exc:
        logger.error("FTP ошибка: %s", exc)
