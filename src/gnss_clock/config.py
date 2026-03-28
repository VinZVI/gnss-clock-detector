"""
Единственное место для всех настроек.

Порядок загрузки:
  1. Значения по умолчанию
  2. Файл .env в корне репозитория (python-dotenv)
  3. Переменные окружения (перекрывают всё)
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    _env = Path(__file__).resolve().parent.parent.parent / ".env"
    if _env.exists():
        load_dotenv(_env)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Пути
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# База данных
# ---------------------------------------------------------------------------
DB_TYPE = os.environ.get("GNSS_DB_TYPE", "sqlite").lower()

if DB_TYPE == "mysql":
    # MySQL конфигурация для PythonAnywhere
    DB_HOST = os.environ.get("GNSS_DB_HOST", "vinzvi.mysql.pythonanywhere-services.com")
    DB_PORT = int(os.environ.get("GNSS_DB_PORT", "3306"))
    DB_NAME = os.environ.get("GNSS_DB_NAME", "vinzvi$gnss-clock")
    DB_USER = os.environ.get("GNSS_DB_USER", "vinzvi")
    DB_PASS = os.environ.get("GNSS_DB_PASS", "")
    
    # SQLAlchemy URI для MySQL
    DATABASE_URI = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
else:
    # SQLite (по умолчанию)
    DB_PATH = Path(os.environ.get("GNSS_DB_PATH", BASE_DIR / "db.sqlite3"))
    DATABASE_URI = f"sqlite:///{DB_PATH}"

# ---------------------------------------------------------------------------
# Источник данных
# ---------------------------------------------------------------------------
DATA_SOURCE = os.environ.get("GNSS_DATA_SOURCE", "auto").lower()

# ---------------------------------------------------------------------------
# NASA Earthdata
# ---------------------------------------------------------------------------
NASA_USER  = os.environ.get("NASA_EARTHDATA_USER", "")
NASA_PASS  = os.environ.get("NASA_EARTHDATA_PASS", "")

# Bearer token — предпочтительный способ (избегает TLS-редиректов на Windows)
# Задайте вручную: NASA_EARTHDATA_TOKEN=eyJ0eXAi...
# Или оставьте пустым — клиент получит токен автоматически через EDL API
NASA_TOKEN = os.environ.get("NASA_EARTHDATA_TOKEN", "")

# Продукт IGS
NASA_PRODUCT = os.environ.get("NASA_PRODUCT", "igu").lower()

# База URL (обновлён после миграции CDDIS → earthdata.nasa.gov, июнь 2025)
NASA_BASE_URL = os.environ.get(
    "NASA_BASE_URL",
    "https://cddis.nasa.gov/archive/gnss/products"   # старый URL (всё ещё работает через редирект)
)
NASA_TIMEOUT  = int(os.environ.get("NASA_TIMEOUT", "60"))

# ---------------------------------------------------------------------------
# FTP GLONASS-IAC
# ---------------------------------------------------------------------------
FTP_HOST    = os.environ.get("GNSS_FTP_HOST",    "ftp.glonass-iac.ru")
FTP_PORT    = int(os.environ.get("GNSS_FTP_PORT", "21"))
FTP_USER    = os.environ.get("GNSS_FTP_USER",    "anonymous")
FTP_PASSWD  = os.environ.get("GNSS_FTP_PASSWD",  "anonymous")
FTP_TIMEOUT = int(os.environ.get("GNSS_FTP_TIMEOUT", "30"))
FTP_BASE    = os.environ.get("GNSS_FTP_BASE", "/MCC/PRODUCTS")
FTP_SUBDIR  = os.environ.get("GNSS_FTP_SUBDIR", "ultra")
PRODUCT_PREFIX = os.environ.get("GNSS_PRODUCT_PREFIX", "Stark")

FILE_PRIORITY = [
    ("{prefix}_{wwwwd}{hh}",    ".clk",  None ),
    ("{prefix}_{wwwwd}{hh}",    ".clk",  ".Z" ),
    ("{prefix}_{wwwwd}{hh}",    ".sp3",  None ),
    ("{prefix}_{wwwwd}{hh}",    ".sp3",  ".Z" ),
    ("{prefix}_1D_{wwwwd}{hh}", ".sp3",  None ),
    ("{prefix}_1D_{wwwwd}{hh}", ".sp3",  ".Z" ),
]

# ---------------------------------------------------------------------------
# ETL
# ---------------------------------------------------------------------------
ETL_DAYS_BACK   = int(os.environ.get("GNSS_ETL_DAYS_BACK",    "3"))
ETL_RETAIN_DAYS = int(os.environ.get("GNSS_ETL_RETAIN_DAYS", "14"))
MAD_THRESHOLD   = float(os.environ.get("GNSS_MAD_THRESHOLD",  "3.0"))

# ---------------------------------------------------------------------------
# Flask
# ---------------------------------------------------------------------------
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
FLASK_HOST  = os.environ.get("FLASK_HOST",  "127.0.0.1")
FLASK_PORT  = int(os.environ.get("FLASK_PORT", "5000"))
SECRET_KEY  = os.environ.get("SECRET_KEY",  "change-me-in-production")
