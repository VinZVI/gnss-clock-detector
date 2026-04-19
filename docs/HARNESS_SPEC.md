# Harness Engineering — Спецификация для gnss-clock-detector

**Документ:** `docs/HARNESS_SPEC.md`  
**Версия:** 1.0 | Дата: апрель 2026  
**Основание:** Методология OpenAI «Harness Engineering: Leveraging Codex in an Agent-First World»

---

## Что такое Harness Engineering и зачем он нужен этому проекту

OpenAI показал: группа из 3 инженеров за 5 месяцев без единой строки вручную написанного кода выпустила продукт из ~1 млн строк (1 500 PR). Ключ — не качество модели, а **harness**: среда, в которой агент работает. Три слоя AI-разработки:

| Слой | Что оптимизирует | Пример |
|------|-----------------|--------|
| Prompt Engineering | Один обмен с моделью | Few-shot, CoT |
| Context Engineering | Что модель видит в окне | RAG, сжатие истории |
| **Harness Engineering** | Весь мир агента на протяжении часов | Инструменты, валидация, архитектурные ограничения |

Для **gnss-clock-detector** harness — это совокупность файлов, линтеров, CI-проверок и документов, которые позволяют агенту (Claude, Codex, Cursor) надёжно расширять кодовую базу без архитектурного дрейфа.

---

## Часть 1. AGENTS.md — карта, не инструкция

### Проблема, которую решаем
OpenAI попытались вложить всё в один большой `AGENTS.md`. Провалилось по 4 причинам:
- Раздутый файл вытесняет контекст задачи
- «Всё важно» = «ничего важного»
- Правила устаревают (правило недели 2 неверно на неделе 8)
- Плоский документ нельзя механически проверить

### Решение для нашего проекта
`AGENTS.md` в корне репозитория — **≤ 100 строк**, только карта. Всё детальное — в `docs/`.

**Создать файл `/AGENTS.md`:**

```markdown
# gnss-clock-detector — Карта для агентов

## Что делает проект
MAD-детектор аномалий часов GNSS-спутников.
Источники: GLONASS-IAC FTP + NASA CDDIS HTTPS → SQLite → Flask API → Chart.js UI

## Архитектура (ОБЯЗАТЕЛЬНО прочитать перед изменениями)
→ [Слоистая архитектура](docs/ARCHITECTURE.md)
→ [Правила зависимостей](docs/ARCHITECTURE.md#dependency-rules)

## Ключевые модули
→ [Карта модулей](docs/MODULE_MAP.md)

## Источники данных
→ [FTP GLONASS-IAC](docs/DATA_SOURCES.md#ftp)
→ [NASA CDDIS HTTPS](docs/DATA_SOURCES.md#nasa)
→ [Форматы файлов](docs/DATA_SOURCES.md#formats)

## Принятые решения
→ [Лог архитектурных решений](docs/ADR.md)

## Как запустить тесты
uv run pytest tests/ -v

## Запрещено
- Добавлять зависимости без записи в ADR.md
- Нарушать порядок слоёв (см. ARCHITECTURE.md)
- Коммитить .env / db.sqlite3 / .token_cache
```

---

## Часть 2. Слоистая архитектура с механической валидацией

### Проблема, которую решаем
Без ограничений агент воспроизводит любые паттерны из репозитория, включая плохие. Архитектурный дрейф происходит незаметно.

### Слои проекта (строгий порядок зависимостей)

```
config.py          ← [1] Конфигурация (только os.environ, Path)
    ↓
models.py          ← [2] Типы данных (SQLAlchemy, dataclasses)
    ↓
utils.py           ← [3] Утилиты (decompress, без бизнес-логики)
gps_time.py        ← [3] Вычисления времени (чистые функции)
parsers.py         ← [3] Парсеры файлов (чистые функции)
    ↓
detector.py        ← [4] Алгоритм MAD (только numpy, без БД)
analytics.py       ← [4] Аналитика (только numpy, без БД)
    ↓
ftp_client.py      ← [5] FTP-транспорт (зависит от config, gps_time, utils)
nasa_client.py     ← [5] HTTPS-транспорт (зависит от config, gps_time, utils)
    ↓
etl.py             ← [6] Оркестрация (зависит от всех слоёв ≤5)
    ↓
app.py             ← [7] Flask API (зависит от всех; только здесь Flask)
```

**Правило:** Модуль слоя N **не может** импортировать из слоя > N.

**Создать файл `docs/ARCHITECTURE.md`** (см. Приложение A).

### Линтер зависимостей (CI-проверка)

**Создать файл `scripts/check_deps.py`:**

```python
"""
Проверяет, что импорты не нарушают порядок слоёв.
Запускается в CI: python scripts/check_deps.py
"""
import ast, sys, pathlib

LAYERS = {
    "config":       1,
    "models":       2,
    "utils":        3,
    "gps_time":     3,
    "parsers":      3,
    "detector":     4,
    "analytics":    4,
    "ftp_client":   5,
    "nasa_client":  5,
    "etl":          6,
    "app":          7,
}

errors = []
src = pathlib.Path("src/gnss_clock")
for pyfile in src.glob("*.py"):
    module = pyfile.stem
    if module not in LAYERS or module.startswith("_"):
        continue
    my_layer = LAYERS[module]
    tree = ast.parse(pyfile.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for dep, dep_layer in LAYERS.items():
                if dep in (node.module or "") and dep_layer > my_layer:
                    errors.append(
                        f"ОШИБКА: {module}.py (слой {my_layer}) "
                        f"импортирует {dep} (слой {dep_layer}). "
                        f"Нарушение: слой {my_layer} не может зависеть от слоя {dep_layer}."
                    )

if errors:
    print("\n".join(errors))
    sys.exit(1)
print(f"✓ Зависимости OK ({len(LAYERS)} модулей проверено)")
```

**Добавить в CI (`.github/workflows/ci.yml`):**

```yaml
- name: Проверка архитектурных зависимостей
  run: python scripts/check_deps.py
```

---

## Часть 3. Документация как единственный источник истины

### Проблема, которую решаем
Если что-то не в контексте агента во время работы — для него этого не существует. Знания в Slack-тредах и головах людей невидимы.

### Структура `docs/`

```
docs/
├── HARNESS_SPEC.md      ← этот файл (мета-документ)
├── ARCHITECTURE.md      ← слои, правила зависимостей, диаграммы
├── MODULE_MAP.md        ← назначение каждого модуля, входы/выходы
├── DATA_SOURCES.md      ← форматы FTP, NASA, примеры имён файлов
├── ADR.md               ← лог архитектурных решений (append-only)
├── ETL_PIPELINE.md      ← поток данных от загрузки до аномалий
└── API_REFERENCE.md     ← все эндпоинты, параметры, примеры ответов
```

### ADR (Architectural Decision Records)

Каждое нетривиальное решение фиксируется в `docs/ADR.md`. Формат:

```markdown
## ADR-001: SQLite вместо PostgreSQL (2026-03)
**Статус:** Принято  
**Контекст:** 1-2 пользователя, данные за 14 дней (~80 MB), нет конкурентной записи  
**Решение:** SQLite + persistent disk на Render ($7/мес)  
**Последствия:** Нельзя масштабировать на > 1 инстанс; переход на Postgres — отдельный ADR

## ADR-002: Async ETL через threading вместо Celery (2026-04)
**Статус:** Принято  
**Контекст:** Gunicorn worker timeout 120s; ETL занимает 2-5 минут  
**Решение:** daemon-поток + polling /api/admin/etl/status/<job_id>  
**Последствия:** Состояние теряется при рестарте процесса; приемлемо для текущей нагрузки

## ADR-003: IGS3 long-name format для NASA файлов (2026-04)
**Статус:** Принято  
**Контекст:** NASA переименовал файлы с GPS-недели 2238 (ноябрь 2022)  
**Решение:** IGS0OPSULT_<YYYYDDD><HH>00_02D_30S_CLK.CLK.gz, 8 анализ-центров  
**Последствия:** Старый формат igu*.sp3.Z не работает с 2022 года

## ADR-004: Bearer Token вместо Basic Auth redirect (2026-04)
**Статус:** Принято  
**Контекст:** ConnectionResetError 10054 на Windows при TLS-редиректах NASA  
**Решение:** EDL API find_or_create_token, кеш в .token_cache  
**Последствия:** Токен истекает через 60 дней; нужен мониторинг

## ADR-005: MAD со скользящим окном (rolling window) (2026-04)
**Статус:** Принято  
**Контекст:** Глобальный MAD некорректен для нестационарных часовых рядов  
**Решение:** window_size=15 точек вокруг каждой; параметр через API  
**Последствия:** Граничные точки имеют меньше соседей (корректно обрабатывается)
```

---

## Часть 4. Автоматическая самооценка — «Evaluator» для ETL

### Проблема, которую решаем
OpenAI установил конкретный порог: сервис должен стартовать менее чем за 800мс. Агенты систематически переоценивают своё качество (self-evaluation bias). Anthropic проверил: три агента (Planner + Generator + Evaluator) производят качественно другой результат, чем один.

### Применение к gnss-clock-detector

**Структурные тесты** — механическая верификация, не зависящая от агента:

**Создать `scripts/structural_tests.py`:**

```python
"""
Структурные тесты репозитория.
Запускаются в CI как самостоятельная проверка (аналог Evaluator-агента).
Проверяют инварианты, которые агент НЕ должен нарушать.
"""
import sys, pathlib, ast, importlib.util, re

ERRORS = []

def check(condition, msg):
    if not condition:
        ERRORS.append(f"FAIL: {msg}")

# 1. AGENTS.md существует и ≤ 100 строк
agents_md = pathlib.Path("AGENTS.md")
check(agents_md.exists(), "AGENTS.md не найден")
if agents_md.exists():
    lines = len(agents_md.read_text().splitlines())
    check(lines <= 100, f"AGENTS.md {lines} строк > 100 (Harness-правило)")

# 2. docs/ содержит обязательные файлы
required_docs = ["ARCHITECTURE.md", "ADR.md", "MODULE_MAP.md",
                 "DATA_SOURCES.md", "ETL_PIPELINE.md"]
for doc in required_docs:
    check(pathlib.Path(f"docs/{doc}").exists(), f"docs/{doc} не найден")

# 3. .env и db.sqlite3 не в git-треке (есть в .gitignore)
gitignore = pathlib.Path(".gitignore").read_text()
for secret in [".env", "db.sqlite3", ".token_cache"]:
    check(secret in gitignore, f"{secret} не защищён .gitignore")

# 4. Каждый модуль src/gnss_clock/*.py имеет docstring
src = pathlib.Path("src/gnss_clock")
for py in src.glob("*.py"):
    if py.name.startswith("_"): continue
    tree = ast.parse(py.read_text())
    has_doc = (isinstance(tree.body[0], ast.Expr) and
               isinstance(tree.body[0].value, ast.Constant))
    check(has_doc, f"{py.name}: нет docstring на уровне модуля")

# 5. NASA_TIMEOUT >= 60 (защита от worker timeout на Render)
config_text = pathlib.Path("src/gnss_clock/config.py").read_text()
timeout_match = re.search(r'NASA_TIMEOUT\s*=.*?(\d+)', config_text)
if timeout_match:
    check(int(timeout_match.group(1)) >= 60,
          f"NASA_TIMEOUT={timeout_match.group(1)} < 60 — риск timeout на Render")

# 6. Версия в pyproject.toml синхронизирована с Changelog в README
pyproject = pathlib.Path("pyproject.toml").read_text()
readme    = pathlib.Path("README.md").read_text()
ver_match = re.search(r'version\s*=\s*"(\d+\.\d+\.\d+)"', pyproject)
if ver_match:
    ver = ver_match.group(1)
    check(f"v{ver}" in readme or ver in readme,
          f"Версия {ver} из pyproject.toml не найдена в README.md")

if ERRORS:
    print("\n".join(ERRORS))
    sys.exit(1)
print(f"✓ Структурные тесты OK ({len(ERRORS)} ошибок)")
```

### ETL Health Check — автоматическая проверка после каждого запуска

**Добавить в `etl.py` функцию `_health_check()`:**

```python
def _health_check(app, stats: dict) -> list[str]:
    """
    Evaluator-слой: проверяет результат ETL.
    Возвращает список предупреждений (не останавливает процесс).
    """
    warnings = []
    
    # 1. Если 0 файлов — возможно источник недоступен
    if stats["files_processed"] == 0:
        warnings.append(
            f"ETL [{stats['source']}]: 0 файлов загружено за {stats.get('elapsed_sec', '?')}с. "
            f"Проверьте доступность источника."
        )
    
    # 2. Если >50% записей дубликаты — возможна проблема дедупликации
    if stats["records_raw"] > 0:
        dup_rate = 1 - (stats["records_new"] / stats["records_raw"])
        if dup_rate > 0.5 and stats["records_new"] > 0:
            warnings.append(
                f"ETL: {dup_rate:.0%} записей — дубликаты. "
                f"Возможно, already_loaded не работает корректно."
            )
    
    # 3. Если нет спутников в БД — данные не попали
    from .models import SatClock
    with app.app_context():
        sat_count = db.session.query(SatClock.sat_id).distinct().count()
        if sat_count == 0:
            warnings.append("БД пуста: ни одного спутника. ETL не записал данные.")
        elif sat_count < 20 and stats["source"] in ("ftp", "auto"):
            warnings.append(
                f"Только {sat_count} спутников (ожидается ≥20 для FTP). "
                f"Возможно, парсер не распознал формат файла."
            )
    
    return warnings
```

---

## Часть 5. Фоновые задачи технического долга

### Проблема, которую решаем
OpenAI запускал фоновые агент-задачи по расписанию для рефакторинга накопившегося долга. Без этого технический долг копится до критической массы.

### Для gnss-clock-detector: автоматические проверки

**GitHub Actions — еженедельная проверка здоровья (`.github/workflows/weekly_health.yml`):**

```yaml
name: Weekly Health Check
on:
  schedule:
    - cron: '0 6 * * 1'  # каждый понедельник 06:00 UTC
  workflow_dispatch:

jobs:
  health:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv pip install -e ".[dev]"
      
      # Структурные тесты
      - name: Структурные тесты
        run: python scripts/structural_tests.py
      
      # Проверка зависимостей
      - name: Архитектурные зависимости
        run: python scripts/check_deps.py
      
      # Юнит-тесты
      - name: Pytest
        run: uv run pytest tests/ -v
      
      # Устаревшие зависимости
      - name: Проверка обновлений
        run: pip list --outdated
```

---

## Часть 6. Управление контекстом агента

### Проблема, которую решаем
«Context anxiety» — агенты начинают срезать углы, когда чувствуют приближение лимита контекста. Cognition (Devin) решили это, ограничив реальное использование до 200K при разрешённом 1M токенов.

### Правила для работы с агентами в этом репозитории

**При открытии новой задачи агент должен:**

1. Прочитать `AGENTS.md` (карта) — **всегда первый шаг**
2. Прочитать релевантный документ из `docs/` — только нужный
3. Прочитать только изменяемые файлы, не весь репозиторий

**Размер контекста по типу задачи:**

| Задача | Файлы для контекста |
|--------|---------------------|
| Исправить баг в парсере | `parsers.py`, `tests/test_parsers.py`, `docs/DATA_SOURCES.md` |
| Добавить API endpoint | `app.py`, `models.py`, `docs/API_REFERENCE.md` |
| Изменить ETL pipeline | `etl.py`, `ftp_client.py` или `nasa_client.py`, `docs/ETL_PIPELINE.md`, `docs/ADR.md` |
| Исправить NASA клиент | `nasa_client.py`, `gps_time.py`, `docs/DATA_SOURCES.md#nasa` |

**Принцип:** Агент не должен читать весь репозиторий для локальных изменений.

---

## Часть 7. Правила PR для агентов

### Что должен содержать каждый PR от агента

```markdown
## Описание изменений
[Что изменено и почему]

## Затронутые слои архитектуры
- [ ] Слой 1 (config)
- [ ] Слой 2-3 (models, utils, parsers)
- [ ] Слой 4 (detector, analytics)
- [ ] Слой 5 (ftp_client, nasa_client)
- [ ] Слой 6 (etl)
- [ ] Слой 7 (app)

## Проверки
- [ ] `python scripts/check_deps.py` — OK
- [ ] `python scripts/structural_tests.py` — OK
- [ ] `uv run pytest tests/ -v` — OK
- [ ] ADR обновлён (если принято архитектурное решение)
- [ ] README/CHANGELOG обновлён (если публичный интерфейс изменился)

## Связанный ADR
[Ссылка или "не требуется"]
```

---

## Часть 8. Мониторинг и обратная связь

### Порог работоспособности (аналог «800мс» из OpenAI)

Для gnss-clock-detector определены следующие пороги:

| Метрика | Норма | Критично |
|---------|-------|---------|
| ETL старт (response time) | < 1с (202 Accepted) | > 5с |
| ETL poll /status | < 200мс | > 2с |
| ETL полное выполнение | < 5 мин | > 10 мин |
| API /api/satellites | < 500мс | > 3с |
| API /api/clock-series | < 2с | > 10с |
| FTP: 0 файлов → NASA fallback | автоматически | — |
| NASA: все 8 анализ-центров 404 | предупреждение в log | — |

**Health check endpoint (добавить в `app.py`):**

```python
@app.route("/api/health")
def health_check():
    """Используется Render.com и UptimeRobot."""
    import time
    t0 = time.time()
    try:
        db.session.execute(db.text("SELECT COUNT(*) FROM sat_clock"))
        db_ok = True
    except Exception:
        db_ok = False
    
    elapsed_ms = int((time.time() - t0) * 1000)
    status = "healthy" if db_ok else "degraded"
    return jsonify({
        "status":     status,
        "db":         "ok" if db_ok else "error",
        "elapsed_ms": elapsed_ms,
    }), (200 if db_ok else 503)
```

---

## Часть 9. Эволюция harness — что удалять по мере роста модели

OpenAI подчёркивают: лучший harness-компонент — тот, который со временем можно удалить. Каждый компонент кодирует ограничение текущей модели.

### Компоненты gnss-clock-detector и условия удаления

| Компонент | Зачем сейчас | Когда удалить |
|-----------|-------------|---------------|
| Async ETL + polling | Gunicorn worker timeout | Когда Render поднимет таймаут или добавим background worker |
| 8 analysis centers для NASA | Нет гарантии публикации от конкретного центра | Когда CDDIS предоставит API листинга директории |
| Bearer token cache (.token_cache) | EDL redirect drops Basic Auth на Windows | Если EDL начнёт поддерживать persistent sessions |
| Rolling window MAD | Глобальный MAD некорректен | Если добавим ML-модель для детекции |
| `already_loaded_files()` | Предотвращает повторную загрузку | Если добавим content-hash в имена файлов |
| `scripts/check_deps.py` | Агенты нарушают слои | Если IDE/IDE-плагин начнёт проверять слои |

---

## Приложение A. Шаблон `docs/ARCHITECTURE.md`

```markdown
# Архитектура gnss-clock-detector

## Слоистая модель зависимостей

[1] config.py          — только os.environ, Path (нет импортов из проекта)
[2] models.py          — SQLAlchemy-модели (зависит от [1])
[3] utils.py           — decompress(), общие утилиты (зависит от [1])
[3] gps_time.py        — чистые функции времени (зависит от [1])
[3] parsers.py         — SP3 и RINEX CLK (зависит от [1])
[4] detector.py        — MAD со скользящим окном (зависит от [1-3])
[4] analytics.py       — метрики стабильности (зависит от [1-3])
[5] ftp_client.py      — FTP-транспорт (зависит от [1-4])
[5] nasa_client.py     — HTTPS-транспорт (зависит от [1-4])
[6] etl.py             — оркестрация (зависит от [1-5])
[7] app.py             — Flask API (зависит от [1-6])

## Правила
1. Слой N может импортировать только из слоёв < N
2. Flask импортируется ТОЛЬКО в app.py
3. Сетевые запросы ТОЛЬКО в ftp_client.py и nasa_client.py
4. Прямые обращения к БД ТОЛЬКО в etl.py и app.py

## Поток данных
FTP / NASA CDDIS
    → ftp_client.py / nasa_client.py (скачивание)
    → parsers.py (текст → list[dict])
    → etl.py (запись в SatClock)
    → detector.py (MAD → SatClockAnomaly)
    → app.py (REST API)
    → index.html (Chart.js)
```

---

## Приложение B. Минимальный `.github/workflows/ci.yml`

```yaml
name: CI
on: [push, pull_request]

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv pip install -e ".[dev]"
      - name: Структурные тесты
        run: python scripts/structural_tests.py
      - name: Архитектурные зависимости
        run: python scripts/check_deps.py
      - name: Pytest
        run: uv run pytest tests/ -v --tb=short
```

---

## Контрольный список внедрения (Harness Checklist)

- [ ] Создан `AGENTS.md` (≤ 100 строк, ссылки на docs/)
- [ ] Создана директория `docs/` с 6 файлами
- [ ] Записаны ADR-001..ADR-005 в `docs/ADR.md`
- [ ] Создан `scripts/check_deps.py`
- [ ] Создан `scripts/structural_tests.py`
- [ ] Создан `.github/workflows/ci.yml`
- [ ] Создан `.github/workflows/weekly_health.yml`
- [ ] Добавлен `/api/health` endpoint в `app.py`
- [ ] Добавлена функция `_health_check()` в `etl.py`
- [ ] Обновлён `render.yaml`: добавлен `healthCheckPath: /api/health`

**Финальный принцип:** Harness — не фиксированная архитектура. Это система, перекалиброванная с каждым новым релизом модели. Первый вопрос после каждого обновления: «Что теперь можно удалить?»
