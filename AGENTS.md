# gnss-clock-detector — Карта для AI-агентов

## Что делает проект
MAD-детектор аномалий часов GNSS-спутников.
Источники: GLONASS-IAC FTP + NASA CDDIS HTTPS → SQLite → Flask API → Chart.js UI.

## Архитектура (обязательно перед изменениями)
→ [Слоистая архитектура и правила зависимостей](docs/ARCHITECTURE.md)

## Карта модулей
→ [Назначение каждого файла](docs/MODULE_MAP.md)

## Источники данных
→ [FTP GLONASS-IAC + NASA CDDIS, форматы файлов](docs/DATA_SOURCES.md)

## Архитектурные решения
→ [Лог ADR — почему так, а не иначе](docs/ADR.md)

## ETL pipeline
→ [Поток данных от загрузки до аномалий](docs/ETL_PIPELINE.md)

## API
→ [Все эндпоинты, параметры, примеры](docs/API_REFERENCE.md)

## Harness Engineering
→ [Как работать с этим репозиторием как агент](docs/HARNESS_SPEC.md)

## Запуск тестов
```bash
uv run pytest tests/ -v
python scripts/check_deps.py
python scripts/structural_tests.py
```

## Запрещено
- Добавлять зависимости без записи в docs/ADR.md
- Нарушать порядок слоёв (docs/ARCHITECTURE.md)
- Импортировать Flask за пределами app.py
- Коммитить .env / db.sqlite3 / .token_cache
