# GNSS Clock Anomaly Detector

MAD-based обнаружение аномалий в часах навигационных спутников.  
Источник данных: `ftp://ftp.glonass-iac.ru/MCC/PRODUCTS/<WWWWD>/ultra/`

**Стек:** Flask · SQLAlchemy · SQLite · numpy · Chart.js · uv

---

## Структура репозитория

```
gnss-clock-detector/
├── pyproject.toml              # манифест uv-проекта
├── wsgi.py                     # WSGI entry point (PythonAnywhere)
├── src/
│   └── gnss_clock/
│       ├── config.py           # все настройки (env-vars)
│       ├── models.py           # SQLAlchemy: SatClock, SatClockAnomaly, EtlLog
│       ├── gps_time.py         # GPS-неделя ↔ UTC, имена файлов
│       ├── ftp_client.py       # FTP-загрузчик с дедупликацией
│       ├── parsers.py          # SP3-c и RINEX CLK парсеры
│       ├── detector.py         # MAD-детектор
│       ├── etl.py              # pipeline + CLI
│       ├── app.py              # Flask app factory + REST API
│       └── static/index.html  # Dashboard (Chart.js)
└── tests/
    ├── test_gps_time.py
    ├── test_parsers.py
    └── test_detector.py
```

---

## Формат файлов на FTP

```
/MCC/PRODUCTS/<WWWWD>/ultra/
    Stark_<WWWWD><HH>.clk       ← RINEX CLK, ~5 мин, ~500 KB  ✓ приоритет
    Stark_<WWWWD><HH>.sp3       ← SP3 ultra-rapid, ~80 KB
    Stark_1D_<WWWWD><HH>.sp3    ← SP3 1-day
```

`WWWW` = GPS-неделя, `D` = день (0=вс…6=сб), `HH` = слот (00/06/12/18 UTC).  
Файлы без сжатия (в отличие от IGS, которые дают `.Z`).

---

## Быстрый старт (локально)

```bash
# 1. Установить uv (если нет)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Создать venv и установить зависимости
cd gnss-clock-detector
uv venv
uv pip install -e ".[dev]"

# 3. Тесты
uv run pytest

# 4. Тестовые данные (без FTP)
uv run python -m gnss_clock.etl --test

# 5. Запуск сервера
FLASK_DEBUG=1 uv run python wsgi.py
# → http://127.0.0.1:5000
```

---

## ETL CLI

```bash
uv run python -m gnss_clock.etl              # FTP, последние 3 дня
uv run python -m gnss_clock.etl --days 7     # FTP, 7 дней
uv run python -m gnss_clock.etl --test       # синтетика (без FTP)
uv run python -m gnss_clock.etl --no-anomaly # только загрузка
```

Переменные окружения:
```
GNSS_FTP_HOST        ftp.glonass-iac.ru
GNSS_FTP_BASE        /MCC/PRODUCTS
GNSS_FTP_SUBDIR      ultra
GNSS_PRODUCT_PREFIX  Stark
GNSS_ETL_DAYS_BACK   3
GNSS_ETL_RETAIN_DAYS 14
GNSS_MAD_THRESHOLD   3.0
GNSS_DB_PATH         ./db.sqlite3
```

---

## REST API

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/api/satellites` | Спутники с числом аномалий |
| GET | `/api/clock-series?sat_id=R01&from=YYYY-MM-DD&to=YYYY-MM-DD` | Ряд + аномалии |
| GET | `/api/clock-anomalies?sat_id=R01&from=...&to=...` | Только выбросы |
| GET | `/api/stats/daily?date=YYYY-MM-DD` | Суточная сводка |
| GET | `/api/etl/status` | Последние 20 запусков ETL |
| POST | `/api/admin/etl` | Ручной запуск ETL (только debug mode) |

---

## Деплой на PythonAnywhere (paid ≥ $5/мес)

> **Free plan не подходит**: FTP заблокирован whitelist-ом.  
> Нужен минимум Developer/Hacker план ($5/мес) — unrestricted internet.

```bash
# 1. Bash console на PythonAnywhere
git clone https://github.com/<you>/gnss-clock-detector.git
cd gnss-clock-detector

# 2. Установить uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Создать venv и установить пакет
uv venv .venv
uv pip install -e .
uv pip install unlzw3   # распаковка .Z если понадобится

# 4. Первый запуск ETL (проверка FTP)
.venv/bin/python -m gnss_clock.etl --days 3

# 5. Web app
#    Web → Add new web app → Flask
#    Source code: /home/<user>/gnss-clock-detector
#    WSGI file:   /home/<user>/gnss-clock-detector/wsgi.py
#    Virtualenv:  /home/<user>/gnss-clock-detector/.venv

# 6. Scheduled task (hourly)
#    Tasks → каждый час
#    Command: /home/<user>/gnss-clock-detector/.venv/bin/python -m gnss_clock.etl
```

### Дисковый бюджет (paid 1 GB)

| Файл | Размер |
|------|--------|
| `.clk` за 1 сутки (4 файла × 500 KB) | ~2 MB |
| `.sp3` за 1 сутки (4 файла × 80 KB) | ~320 KB |
| SQLite (14 дней, ~5 спутников, 5 мин шаг) | ~15 MB |

Всего на диске — **< 50 MB** при `GNSS_ETL_RETAIN_DAYS=14`.

---

## Примечания по архитектуре ETL

**Проблема**: файлы выходят каждые 6 часов, scheduled task раз в час.  
**Решение**: `EtlLog` хранит имена загруженных файлов.  
`iter_new_files()` сначала запрашивает `already_loaded` из БД, потом сравнивает  
с листингом FTP — скачивает только новые.  
Стоимость холостого запуска: 1 FTP-соединение + `NLST` за каждый каталог ≈ **< 1 сек**.
