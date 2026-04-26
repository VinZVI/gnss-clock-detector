# API Справочник

## Публичные эндпоинты

### Дашборд и Статика
- `GET /` — Главная страница (Дашборд).
- `GET /satellite/<sat_id>` — Страница детальной аналитики конкретного спутника.
- `GET /admin/etl` — Панель управления ETL (SPA-вид).
- `GET /static/<path:filename>` — Статические файлы (JS, CSS, изображения).

### Данные и Аналитика
- `GET /api/satellites` — Список всех спутников, имеющихся в БД, с количеством записей.
- `GET /api/satellites/<sat_id>/meta` — Метаданные спутника (тип, дата запуска, номер слота).
- `GET /api/satellites/<sat_id>/history` — История статусов (события из HLT-файлов).
- `GET /api/satellites/<sat_id>/cache` — Кэшированные результаты ежедневной аналитики.
- `GET /api/data/<sat_id>` — Основной эндпоинт для получения временного ряда.
  - **Query параметры:**
    - `type`: `final`, `rapid` (default), `ultra`.
    - `from`, `to`: даты в формате `YYYY-MM-DD`.
    - `threshold`: порог MAD (default 3.0).
    - `window_size`: размер окна MAD (default 15).

## Администрирование (ETL)

- `GET /api/etl/status` — История последних 20 запусков ETL с результатами.
- `POST /api/admin/etl` — Запуск процесса загрузки данных в фоновом потоке.
  - **Body (JSON):** `{"source": "ftp" | "nasa"}`.
- `GET /api/admin/etl/status` — Текущий статус запущенного фонового процесса (running, completed, failed).
