"""
HTTPS-клиент для NASA CDDIS.

Аутентификация — два метода, выбираются автоматически:
  1. Bearer Token  — предпочтительный, решает ConnectionResetError 10054 на Windows
     Кешируется в .token_cache (файл в корне репо, не в git)
  2. Basic Auth + redirect — запасной вариант

Два формата имён файлов IGS:
  Legacy (до GPS-недели 2238):  igu<WWWW><D>_<HH>.sp3.Z
  IGS3   (с GPS-недели 2238):   IGS0OPSULT_<YYYYDDD><HH>00_02D_15M_ORB.SP3.gz
  Текущий год 2026 → используем IGS3.

Документация:
  https://urs.earthdata.nasa.gov/documentation/for_users/data_access/python
  https://urs.earthdata.nasa.gov/documentation/for_users/user_token
"""

from __future__ import annotations
import base64
import gzip
import io
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterator

import requests

from . import config
from .gps_time import utc_to_gps_week, slot_for, SLOT_HOURS
from .utils import decompress as _decompress

logger = logging.getLogger(__name__)

_EDL_TOKEN_URL = "https://urs.earthdata.nasa.gov/api/users/find_or_create_token"
_TOKEN_CACHE   = Path(__file__).resolve().parent.parent.parent / ".token_cache"


# ---------------------------------------------------------------------------
# Bearer Token: получение и дисковый кеш (60 дней)
# ---------------------------------------------------------------------------

def _get_bearer_token() -> Optional[str]:
    """
    Возвращает Bearer token. Порядок:
      1. NASA_EARTHDATA_TOKEN из .env (ручной)
      2. Файловый кеш .token_cache
      3. EDL API (find_or_create_token) → кешируем на диск
    """
    # 1. Ручной токен из .env
    if config.NASA_TOKEN:
        return config.NASA_TOKEN

    if not config.NASA_USER or not config.NASA_PASS:
        return None

    # 2. Файловый кеш
    try:
        if _TOKEN_CACHE.exists():
            cached = json.loads(_TOKEN_CACHE.read_text())
            if time.time() < cached.get("expires_ts", 0) - 5 * 86400:
                logger.debug("NASA: токен из кеша")
                return cached["token"]
    except Exception:
        pass

    # 3. Запрос через EDL API
    creds = base64.b64encode(f"{config.NASA_USER}:{config.NASA_PASS}".encode()).decode()
    try:
        resp = requests.post(
            _EDL_TOKEN_URL,
            headers={"Authorization": f"Basic {creds}"},
            timeout=30,
        )
        resp.raise_for_status()
        data  = resp.json()
        token = data.get("access_token") or data.get("token")
        if not token:
            logger.warning("EDL API: токен не найден в ответе %s", data)
            return None
        # Кешируем
        try:
            _TOKEN_CACHE.write_text(json.dumps({
                "token":      token,
                "expires_ts": time.time() + 60 * 86400,
            }))
            logger.info("NASA: Bearer token получен и закеширован (60 дней)")
        except Exception as e:
            logger.debug("Не удалось сохранить .token_cache: %s", e)
        return token
    except requests.exceptions.RequestException as exc:
        logger.warning("EDL API: %s — fallback на Basic Auth", exc)
        return None


def invalidate_token_cache() -> None:
    """Сбрасывает кеш токена (вызывается при 401)."""
    try:
        if _TOKEN_CACHE.exists():
            _TOKEN_CACHE.unlink()
            logger.info("NASA: .token_cache удалён")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Сессии
# ---------------------------------------------------------------------------

class _BearerSession(requests.Session):
    def __init__(self, token: str):
        super().__init__()
        self.headers.update({"Authorization": f"Bearer {token}"})


class _BasicRedirectSession(requests.Session):
    """Basic Auth с правильной обработкой OAuth-редиректов NASA."""
    AUTH_HOST = "urs.earthdata.nasa.gov"

    def __init__(self, username: str, password: str):
        super().__init__()
        self.auth = (username, password)

    def rebuild_auth(self, prepared_request, response):
        if "Authorization" in prepared_request.headers:
            orig  = requests.utils.urlparse(response.request.url).hostname
            redir = requests.utils.urlparse(prepared_request.url).hostname
            if orig != redir and redir != self.AUTH_HOST:
                del prepared_request.headers["Authorization"]


def _make_session() -> Optional[requests.Session]:
    """Bearer (предпочтительно) → Basic redirect → None."""
    if not config.NASA_USER and not config.NASA_TOKEN:
        logger.warning("NASA_EARTHDATA_USER / NASA_EARTHDATA_TOKEN не заданы в .env")
        return None

    token = _get_bearer_token()
    if token:
        return _BearerSession(token)

    if config.NASA_USER and config.NASA_PASS:
        logger.info("NASA: Bearer недоступен, используем Basic Auth")
        return _BasicRedirectSession(config.NASA_USER, config.NASA_PASS)

    return None


# ---------------------------------------------------------------------------
# Формирование имён файлов
# ---------------------------------------------------------------------------

# Analysis Center codes for ultra-rapid products (most common ones)
_ANALYSIS_CENTERS = ['COD', 'EMR', 'GFZ', 'TUG', 'SHA', 'JPL', 'MIT', 'ESA']

def _igs3_name(dt_utc: datetime, slot_h: int, ftype: str) -> list[str]:
    """
    Имена файлов нового формата IGS3 (с недели 2238, ноябрь 2022).
    ftype: 'CLK' или 'SP3'
    
    Актуальный формат для ultra-rapid (igu):
      - CLK: COD0OPSULT_20260860600_02D_05M_CLK.CLK.gz (5-минутные)
      - SP3: COD0OPSULT_20260860600_02D_05M_ORB.SP3.gz (5-минутные)
    
    Формат времени: YYYYDOYHHMM (год + день года + час + минута)
    Для ultra-rapid минуты = 00 для слотов 00,06,12,18 UTC
    """
    doy  = dt_utc.timetuple().tm_yday
    yyyy = dt_utc.year
    # Формируем timestamp: YYYYDOYHHMM
    # Для слотов 00,06,12,18 → минуты = 00
    timestamp = f"{yyyy}{doy:03d}{slot_h:02d}00"
    
    names = []
    # Пробуем несколько анализ центров по порядку приоритета
    for ac in _ANALYSIS_CENTERS:
        if ftype == "CLK":
            fname = f"{ac}0OPSULT_{timestamp}_02D_05M_CLK.CLK.gz"
        else:  # SP3
            fname = f"{ac}0OPSULT_{timestamp}_02D_05M_ORB.SP3.gz"
        names.append(fname)
    
    return names


def _legacy_name(gps_week: int, gps_dow: int, slot_h: int, ftype: str) -> str:
    """
    Имена файлов старого формата (до недели 2238).
    ftype: 'CLK' или 'SP3'
    """
    ext = "clk" if ftype == "CLK" else "sp3"
    return f"igu{gps_week:04d}{gps_dow}_{slot_h:02d}.{ext}.gz"


def _candidate_urls(gps_week: int, gps_dow: int, slot_h: int) -> list[tuple[str, str]]:
    """
    Возвращает [(url, filename), ...] в порядке приоритета.
    Пробует IGS3-имена (актуальные) от разных анализ центров + legacy-имена (запасные).
    """
    base = config.NASA_BASE_URL.rstrip("/")
    week_dir = f"{gps_week:04d}"

    # Восстанавливаем UTC-дату из GPS-недели
    from datetime import datetime, timezone, timedelta
    _GPS_EPOCH = datetime(1980, 1, 6, tzinfo=timezone.utc)
    dt_utc = _GPS_EPOCH + timedelta(weeks=gps_week, days=gps_dow, hours=slot_h)

    candidates: list[tuple[str, str]] = []

    # IGS3 (приоритет для 2022+) - пробуем несколько анализ центров
    if gps_week >= 2238:
        for ftype in ("CLK", "SP3"):
            # Получаем список имён файлов от разных анализ центров
            fnames = _igs3_name(dt_utc, slot_h, ftype)
            for fname in fnames:
                candidates.append((f"{base}/{week_dir}/{fname}", fname))

    # Legacy (всегда добавляем как запасной вариант)
    for ftype in ("CLK", "SP3"):
        fname = _legacy_name(gps_week, gps_dow, slot_h, ftype)
        candidates.append((f"{base}/{week_dir}/{fname}", fname))

    return candidates


# ---------------------------------------------------------------------------
# Скачивание + распаковка
# ---------------------------------------------------------------------------


def _download_url(session: requests.Session, url: str, fname: str) -> Optional[bytes]:
    try:
        resp = session.get(url, timeout=config.NASA_TIMEOUT, stream=True)

        if resp.status_code == 401:
            logger.warning("NASA 401 (%s) — сброс token cache", fname)
            invalidate_token_cache()
            return None
        if resp.status_code == 404:
            return None

        resp.raise_for_status()

        buf = io.BytesIO()
        for chunk in resp.iter_content(chunk_size=65536):
            buf.write(chunk)
        raw = buf.getvalue()
        logger.info("  ↓ NASA %s  (%s байт)", fname, f"{len(raw):,}")
        return raw

    except requests.exceptions.ConnectionError as exc:
        logger.error(
            "  NASA ConnectionError %s: %s\n"
            "  → Убедитесь что NASA_EARTHDATA_TOKEN задан в .env "
            "(Bearer token избегает TLS-редиректов на Windows)",
            fname, exc,
        )
        return None
    except requests.exceptions.RequestException as exc:
        logger.error("  NASA %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def check_credentials() -> dict:
    """Проверяет доступность NASA CDDIS. Возвращает {ok, message, auth_method}."""
    if not config.NASA_USER and not config.NASA_TOKEN:
        return {
            "ok": False,
            "message": "NASA_EARTHDATA_USER или NASA_EARTHDATA_TOKEN не заданы в .env",
            "auth_method": "none",
        }

    token      = _get_bearer_token()
    auth_method = "bearer" if token else "basic"

    session = _make_session()
    if session is None:
        return {"ok": False, "message": "Не удалось создать сессию", "auth_method": "none"}

    test_url = config.NASA_BASE_URL.rstrip("/") + "/"
    try:
        resp = session.get(test_url, timeout=15)
        ok = resp.status_code not in (401, 403)
        return {
            "ok":          ok,
            "message":     f"HTTP {resp.status_code} ({auth_method})",
            "auth_method": auth_method,
        }
    except requests.exceptions.RequestException as exc:
        return {"ok": False, "message": str(exc), "auth_method": auth_method}


def iter_new_files(
    days_back: int = config.ETL_DAYS_BACK,
    already_loaded: set[str] | None = None,
) -> Iterator[tuple[str, str]]:
    """Итерирует слоты, скачивает с CDDIS, возвращает (filename, text)."""
    if already_loaded is None:
        already_loaded = set()

    session = _make_session()
    if session is None:
        return

    now = datetime.now(timezone.utc)
    total_slots = days_back * (24 // SLOT_HOURS)
    cur = now.replace(hour=slot_for(now), minute=0, second=0, microsecond=0)
    slots = []
    for i in range(total_slots):
        t = cur - timedelta(hours=i * SLOT_HOURS)
        w, d = utc_to_gps_week(t)
        slots.append((w, d, t.hour, t))

    auth_type = "bearer" if isinstance(session, _BearerSession) else "basic"
    logger.info("NASA CDDIS: %d слотов за %d дней (%s, %s)",
                len(slots), days_back, config.NASA_PRODUCT, auth_type)

    for gps_week, gps_dow, slot_h, _ in slots:
        logger.debug("Checking GPS week %d day %d slot %02d", gps_week, gps_dow, slot_h)
        for url, fname in _candidate_urls(gps_week, gps_dow, slot_h):
            logger.debug("  Trying: %s", fname)
            if fname in already_loaded:
                logger.debug("  пропуск (уже загружен): %s", fname)
                break

            raw = _download_url(session, url, fname)
            if raw is None:
                continue

            text = _decompress(raw, fname)
            if text is None:
                continue

            yield fname, text
            break
