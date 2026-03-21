"""
Единственное место для всех настроек.
Переменные окружения переопределяют дефолты.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Пути
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent   # корень репозитория
DB_PATH  = Path(os.environ.get("GNSS_DB_PATH", BASE_DIR / "db.sqlite3"))

# ---------------------------------------------------------------------------
# FTP
# ---------------------------------------------------------------------------
FTP_HOST    = os.environ.get("GNSS_FTP_HOST",    "ftp.glonass-iac.ru")
FTP_PORT    = int(os.environ.get("GNSS_FTP_PORT", "21"))
FTP_USER    = os.environ.get("GNSS_FTP_USER",    "anonymous")
FTP_PASSWD  = os.environ.get("GNSS_FTP_PASSWD",  "anonymous")
FTP_TIMEOUT = int(os.environ.get("GNSS_FTP_TIMEOUT", "30"))

# Базовый путь на FTP: /MCC/PRODUCTS/<WWWWD>/ultra/
FTP_BASE    = os.environ.get("GNSS_FTP_BASE", "/MCC/PRODUCTS")
FTP_SUBDIR  = os.environ.get("GNSS_FTP_SUBDIR", "ultra")   # ultra | rapid | final

# Имя продукта (префикс файлов) — "Stark" судя по листингу
PRODUCT_PREFIX = os.environ.get("GNSS_PRODUCT_PREFIX", "Stark")

# ---------------------------------------------------------------------------
# Стратегия выбора файлов
#
# На FTP лежат файлы вида:
#   Stark_1D_<WWWWD><HH>.sp3   — SP3 1-day (15-мин шаг часов)
#   Stark_<WWWWD><HH>.clk      — RINEX CLK ultra-rapid (~5 мин)  ← приоритет
#   Stark_<WWWWD><HH>.sp3      — SP3 ultra-rapid (6-час окно)
#
# Файлы выходят каждые 6 часов: слоты 00, 06, 12, 18 UTC.
# Каждый файл покрывает следующие ~6 часов.
# ---------------------------------------------------------------------------
# Порядок: (суффикс-шаблона, расширение, сжатие)
# сжатие: None | '.Z' | '.gz'
FILE_PRIORITY = [
    # шаблон              расширение   сжат?
    ("{prefix}_{wwwwd}{hh}",  ".clk",  None ),   # RINEX CLK, без архива
    ("{prefix}_{wwwwd}{hh}",  ".clk",  ".Z" ),   # RINEX CLK сжатый
    ("{prefix}_{wwwwd}{hh}",  ".sp3",  None ),   # SP3 ultra
    ("{prefix}_{wwwwd}{hh}",  ".sp3",  ".Z" ),
    ("{prefix}_1D_{wwwwd}{hh}", ".sp3", None ),  # SP3 1-day
    ("{prefix}_1D_{wwwwd}{hh}", ".sp3", ".Z" ),
]

# ---------------------------------------------------------------------------
# ETL
# ---------------------------------------------------------------------------
ETL_DAYS_BACK     = int(os.environ.get("GNSS_ETL_DAYS_BACK",     "3"))   # глубина загрузки
ETL_RETAIN_DAYS   = int(os.environ.get("GNSS_ETL_RETAIN_DAYS",  "14"))   # хранить в БД
MAD_THRESHOLD     = float(os.environ.get("GNSS_MAD_THRESHOLD",   "3.0"))

# ---------------------------------------------------------------------------
# Flask
# ---------------------------------------------------------------------------
FLASK_DEBUG  = os.environ.get("FLASK_DEBUG", "0") == "1"
FLASK_HOST   = os.environ.get("FLASK_HOST",  "127.0.0.1")
FLASK_PORT   = int(os.environ.get("FLASK_PORT", "5000"))
SECRET_KEY   = os.environ.get("SECRET_KEY",  "change-me-in-production")
