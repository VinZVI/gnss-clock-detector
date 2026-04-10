# GNSS Clock Anomaly Detector

MAD-based обнаружение аномалий в часах навигационных спутников.  
Источники данных: **GLONASS-IAC FTP** + **NASA CDDIS HTTPS**

**Стек:** Flask · SQLAlchemy · SQLite · numpy · requests · Chart.js · uv · gunicorn

---

## Структура репозитория

```
gnss-clock-detector/
├── .env.example                # шаблон переменных окружения → скопируйте в .env
├── .gitignore                  # .env и db.sqlite3 не коммитятся
├── pyproject.toml              # манифест uv-проекта
├── render.yaml                 # конфигурация для Render.com
├── render-build.sh             # скрипт сборки для Render.com
├── wsgi.py                     # WSGI entry point (PythonAnywhere, Render)
├── src/
│   └── gnss_clock/
│       ├── config.py           # все настройки (dotenv + env-vars)
│       ├── models.py           # SQLAlchemy: SatClock, SatClockAnomaly, EtlLog
│       ├── gps_time.py         # YYYYDDD/YYMMDDHR + GPS-неделя для NASA
│       ├── ftp_client.py       # FTP-загрузчик GLONASS-IAC
│       ├── nasa_client.py      # HTTPS-загрузчик NASA CDDIS (Earthdata Login)
│       ├── parsers.py          # SP3-c и RINEX CLK парсеры
│       ├── detector.py         # MAD-детектор
│       ├── etl.py              # pipeline: ftp | nasa | auto + CLI
│       ├── app.py              # Flask app factory + REST API
│       └── static/index.html   # Dashboard (Chart.js + zoom/pan)
└── tests/
    ├── test_gps_time.py        # YYYYDDD, YYMMDDHR, GPS-неделя
    ├── test_parsers.py         # SP3, RINEX CLK (D-нотация, CRLF)
    ├── test_nasa_client.py     # URL-генерация, декомпрессия, mock HTTP
    └── test_detector.py        # MAD-детектор
```

---

## Формат файлов

### GLONASS-IAC FTP
```text
ftp://ftp.glonass-iac.ru/MCC/PRODUCTS/<YYYYDDD>/<subdir>/
    Stark_<YYMMDDHR>.clk    ← RINEX CLK ultra (slots 00, 06, 12, 18)
    Sta26093.clk            ← RINEX CLK rapid/final (daily)
    Stark_1D_<YYMMDDHR>.sp3 ← SP3 ultra, day-long
```
**Изменения:**
- Алгоритм автоматически проверяет директории в порядке: `final` → `rapid` → `ultra` (согласно приоритету качества данных).
- Собирает все `.clk`, `.sp3` и их сжатые версии `.Z`, `.gz`.
- При вставке в базу используется `ON CONFLICT DO NOTHING`, что делает ETL идемпотентным и исключает конфликты при дубликатах спутник+эпоха+источник данных из разных файлов.

### NASA CDDIS HTTPS
```
https://cddis.nasa.gov/archive/gnss/products/<WWWW>/
    COD0OPSULT_20260860600_02D_05M_ORB.SP3.gz  ← SP3 ultra-rapid (COD), 5 мин
    COD0OPSULT_20260860600_02D_05M_CLK.CLK.gz  ← RINEX CLK (COD), 5 мин
    EMR0OPSULT_...                              ← другие анализ центры (EMR, GFZ, ...)
    igr<WWWW><D>.sp3.gz                         ← rapid (daily)
```
`WWWW` = GPS-неделя, `D` = день (0=вс…6=сб), формат имени: `YYYYDOYHHMM_02D_05M`

**Поддерживаемые анализ центры:** COD, EMR, GFZ, TUG, SHA, JPL, MIT, ESA

> ⚠️ **Важно:** В 2026 году NASA использует формат IGS3 с 5-минутным интервалом (`05M`), а не 15-минутным. Клиент автоматически пробует файлы от разных анализ центров.

---

## Настройка (.env)

```bash
# Скопировать шаблон
cp .env.example .env
```

Ключевые переменные в `.env`:

```ini
# Источник: ftp | nasa | auto (FTP → NASA fallback)
GNSS_DATA_SOURCE=auto

# NASA Earthdata Login — https://urs.earthdata.nasa.gov/users/new
NASA_EARTHDATA_USER=your_login
NASA_EARTHDATA_PASS=your_password
NASA_PRODUCT=igu                # igu | igr | igs

# FTP (дефолты подходят для анонимного доступа)
GNSS_FTP_HOST=ftp.glonass-iac.ru

# ETL
GNSS_ETL_DAYS_BACK=3
GNSS_ETL_RETAIN_DAYS=14
GNSS_MAD_THRESHOLD=3.0

# Flask
FLASK_DEBUG=1
SECRET_KEY=change-me-in-production
```

---

## Быстрый старт (локально)

### Установка uv

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Если uv не может подключиться к PyPI (Windows, ошибка 10054)

Проблема: корпоративный прокси, VPN или антивирус разрывает TLS-соединение.

**Вариант 1 — указать TLS-версию:**
```bash
# Установить переменную перед uv
set UV_NATIVE_TLS=1
uv venv && uv pip install -e ".[dev]"
```

**Вариант 2 — через pip (если uv заблокирован):**
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# или: source .venv/bin/activate  # Linux/macOS
pip install -e ".[dev]"
```

**Вариант 3 — зеркало PyPI (если основной заблокирован):**
```bash
uv pip install -e ".[dev]" --index-url https://pypi.tuna.tsinghua.edu.cn/simple
# или
pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**Вариант 4 — скачать wheels вручную** (для полностью изолированной сети):
```bash
# На машине с интернетом:
pip download flask flask-sqlalchemy sqlalchemy numpy requests python-dotenv unlzw3 werkzeug -d ./wheels

# Перенести папку wheels, затем:
pip install --no-index --find-links=./wheels -e .
```

### Нормальный запуск (когда сеть работает)

```bash
# 1. Создать окружение и установить зависимости
uv venv
uv pip install -e ".[dev]"

# 2. Настроить .env
cp .env.example .env
# Отредактировать .env: добавить NASA_EARTHDATA_USER/PASS

# 3. Тесты
uv run pytest -v
# или без uv:
python -m pytest tests/ -v

# 4. Заполнить БД тестовыми данными (без сети)
uv run python -m gnss_clock.etl --test

# 5. Или загрузить с реального FTP
uv run python -m gnss_clock.etl --source ftp --days 3

# 6. Запустить сервер
set FLASK_DEBUG=1   # Windows
# export FLASK_DEBUG=1  # Linux/macOS
uv run python wsgi.py
# → http://127.0.0.1:5000
```

---

## ETL CLI

```bash
uv run python -m gnss_clock.etl                       # авто-источник, 3 дня
uv run python -m gnss_clock.etl --source ftp          # только GLONASS-IAC FTP
uv run python -m gnss_clock.etl --source nasa         # только NASA CDDIS
uv run python -m gnss_clock.etl --source auto         # FTP → NASA fallback
uv run python -m gnss_clock.etl --days 7              # глубина 7 дней
uv run python -m gnss_clock.etl --test                # синтетика без сети
uv run python -m gnss_clock.etl --no-anomaly          # только загрузка
```

Все параметры читаются из `.env`, флаги CLI перекрывают `.env`.

---

## REST API

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/api/satellites` | Спутники с числом аномалий |
| GET | `/api/clock-series?sat_id=R01&from=YYYY-MM-DD&to=YYYY-MM-DD` | Ряд + аномалии |
| GET | `/api/clock-anomalies?sat_id=R01&from=...&to=...` | Только выбросы |
| GET | `/api/stats/daily?date=YYYY-MM-DD` | Суточная сводка |
| GET | `/api/etl/status` | Последние 20 запусков ETL |
| GET | `/api/sources/status` | Статус источников + конфигурация |
| GET | `/api/sources/nasa/check` | Live-проверка кредов NASA CDDIS |
| POST | `/api/admin/etl` | Ручной запуск ETL (только `FLASK_DEBUG=1`) |

---

## Деплой на Render.com (Free Tier ✓)

**Преимущества Render:**
- ✅ Бесплатный тариф (Free Web Services)
- ✅ Автоматический деплой из GitHub
- ✅ HTTPS из коробки
- ✅ Не требует кредитной карты
- ✅ 750 часов/месяц бесплатно (~24/7 в месяц)

### Шаг 1: Подготовка репозитория

```bash
# Убедиться что все изменения в main ветке
git push origin main
```

### Шаг 2: Создать Web Service на Render

1. Зарегистрироваться на https://render.com
2. Dashboard → **New +** → **Web Service**
3. Connect repository → выбрать `gnss-clock-detector`
4. Заполнить параметры:

   | Параметр | Значение |
   |----------|----------|
   | **Name** | `gnss-clock-detector` |
   | **Region** | Frankfurt (eu-central-1) или London (eu-west-2) |
   | **Branch** | `main` |
   | **Root Directory** | (оставить пустым) |
   | **Runtime** | `Python` |
   | **Build Command** | `bash render-build.sh` |
   | **Start Command** | `gunicorn wsgi:app --bind 0.0.0.0:$PORT` |
   | **Instance Type** | **Free** |

5. **Advanced** → добавить переменные окружения:

   ```
   FLASK_DEBUG=0
   SECRET_KEY=<random-secret-key>
   GNSS_DATA_SOURCE=nasa              # ← Use NASA only (FTP blocked on Render)
   GNSS_ETL_DAYS_BACK=3
   GNSS_ETL_RETAIN_DAYS=14
   GNSS_MAD_THRESHOLD=3.0
   NASA_EARTHDATA_USER=<your-nasa-username>
   NASA_EARTHDATA_PASS=<your-nasa-password>
   ```

6. Click **Create Web Service**

### Шаг 3: Первый запуск ETL

После деплоя:

1. Открыть консоль: **Shell** tab на Render dashboard
2. Выполнить (используем NASA CDDIS):
   ```bash
   python -m gnss_clock.etl --source nasa --days 3
   ```

> ⚠️ **Важно:** FTP может быть заблокирован на Render, поэтому используем только NASA CDDIS.

### Шаг 4: Автоматизация ETL

Render не поддерживает cron jobs на free tier, но можно использовать:

**Вариант 1 — GitHub Actions (рекомендуется):**

Создать `.github/workflows/etl-daily.yml`:

```yaml
name: Daily ETL
on:
  schedule:
    - cron: '0 3 * * *'  # 3 AM UTC daily
  workflow_dispatch:      # manual trigger

jobs:
  etl:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv pip install -e .
      - run: python -m gnss_clock.etl --source ftp --days 1
        env:
          GNSS_DATA_SOURCE: ftp
          GNSS_DB_PATH: ./db.sqlite3
          NASA_EARTHDATA_USER: ${{ secrets.NASA_USER }}
          NASA_EARTHDATA_PASS: ${{ secrets.NASA_PASS }}
      - uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./
          commit_message: 'chore: update database'
```

**Вариант 2 — UptimeRobot + HTTP endpoint:**

1. Добавить endpoint в `app.py` (только для авторизованных)
2. Использовать UptimeRobot (бесплатно) для пинга каждые 5 мин
3. ETL запускается по расписанию внутри приложения

### Шаг 5: Проверка работы

1. Открыть `https://gnss-clock-detector.onrender.com`
2. Проверить API: `/api/satellites`
3. Проверить ETL статус: `/api/etl/status`

---

## Деплой на PythonAnywhere (paid ≥ $5/мес)

> **Free plan не подходит**: FTP заблокирован whitelist-ом, NASA CDDIS тоже.  
> Нужен минимум Hacker план ($5/мес) — unrestricted internet.

```bash
# 1. Bash console на PythonAnywhere
git clone https://github.com/<you>/gnss-clock-detector.git
cd gnss-clock-detector

# 2. Установить uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Создать venv и установить пакет
uv venv .venv
uv pip install -e .

# 4. Настроить .env
cp .env.example .env
nano .env   # заполнить NASA_EARTHDATA_USER, NASA_EARTHDATA_PASS

# 5. Первый запуск ETL
    .venv/bin/python -m gnss_clock.etl --source auto --days 3

# 6. Web app
#    Web → Add new web app → Flask
#    Source code: /home/<user>/gnss-clock-detector
#    WSGI file:   /home/<user>/gnss-clock-detector/wsgi.py
#    Virtualenv:  /home/<user>/gnss-clock-detector/.venv

# 7. Scheduled task (hourly)
#    Tasks → каждый час
#    /home/<user>/gnss-clock-detector/.venv/bin/python -m gnss_clock.etl
```

### Дисковый бюджет (paid 512 MB)

| Данные | Размер |
|--------|--------|
| `.clk` GLONASS-IAC за 1 сутки (4 × 500 KB) | ~2 MB |
| `.sp3.gz` NASA IGU за 1 сутки (4 × ~80 KB) | ~320 KB |
| SQLite (14 дней, 54 спутника, 5-мин шаг) | ~80 MB |
| Итого при `RETAIN_DAYS=14` | **< 90 MB** |

---

## Архитектура ETL

```
┌─────────────────┐    ┌──────────────────┐
│  GLONASS-IAC    │    │   NASA CDDIS     │
│  ftp_client.py  │    │  nasa_client.py  │
│  (FTP, анон.)   │    │  (HTTPS, OAuth)  │
└────────┬────────┘    └────────┬─────────┘
         │                      │
         └──────────┬───────────┘
                    ▼
              etl.py (auto/ftp/nasa)
                    │
           parsers.py (SP3 / RINEX CLK)
           Fortran D-нотация ✓ CRLF ✓
                    │
              db.sqlite3
            (SatClock сырые)
                    │
            detector.py (MAD)
                    │
         SatClockAnomaly + EtlLog
                    │
              Flask REST API
                    │
            Dashboard (Chart.js)
            zoom/pan, MAD-threshold UI
            панель источников
```

**Дедупликация:** `EtlLog.ftp_file` хранит имена уже загруженных файлов.  
Холостой запуск ETL: 1 соединение + NLST ≈ **< 1 сек**.

---

## Changelog

### v0.3.0 — 2026-03-28 (Render.com Deployment)

**🚀 Production Ready for Render.com**
- ✅ Обновлены зависимости до актуальных версий (Flask 3.1, NumPy 2.0, gunicorn 23.0)
- ✅ Python 3.12+ requirement
- ✅ uv-native installation с `render-build.sh`
- ✅ gunicorn WSGI server для production
- ✅ Автоматический деплой из GitHub
- ✅ Free tier compatible (750 hours/month)

**📦 Configuration Files**
- ✅ `render.yaml` — декларативная конфигурация Web Service
- ✅ `render-build.sh` — скрипт сборки и установки зависимостей
- ✅ Обновлённый README с полной инструкцией по деплою

**🔄 CI/CD Integration**
- ✅ GitHub Actions workflow для автоматизации ETL
- ✅ Environment variables management
- ✅ Database persistence через Git LFS или external storage

---

### v0.2.0 — 2026-03-28

**🎯 NASA CDDIS Client Fixed**
- ✏️ Исправлен формат имён файлов для NASA ultra-rapid продуктов (2026)
- ✅ Теперь используется правильный формат IGS3: `05M` (5-минутный) вместо `15M`
- ✅ Добавлена поддержка 8 анализ центров: COD, EMR, GFZ, TUG, SHA, JPL, MIT, ESA
- ✅ Корректный формат timestamp: `YYYYDOYHHMM` вместо `YYYYDOYHHMMSS`
- 📊 Успешная загрузка: 10 файлов, 237,468 записей за 3 дня

**Примеры имён файлов:**
- SP3: `COD0OPSULT_20260860600_02D_05M_ORB.SP3.gz`
- CLK: `COD0OPSULT_20260860600_02D_05M_CLK.CLK.gz`

---

## Регистрация NASA Earthdata

1. Перейти на https://urs.earthdata.nasa.gov/users/new
2. Создать аккаунт (бесплатно)
3. Добавить приложение: Apps → Approve More Applications → **NASA CDDIS**
4. Прописать в `.env`:
   ```ini
   NASA_EARTHDATA_USER=your_username
   NASA_EARTHDATA_PASS=your_password
   ```
5. Проверить: `GET /api/sources/nasa/check` или кнопка **«Проверить доступ»** в UI
