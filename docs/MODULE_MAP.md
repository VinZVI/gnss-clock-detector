# Карта модулей

| Модуль | Слой | Назначение | Входы | Выходы |
|--------|------|-----------|-------|--------|
| `config.py` | 1 | Все настройки (env vars) | os.environ, .env | константы Python |
| `models.py` | 2 | SQLAlchemy ORM модели | — | SatClock, EtlLog |
| `utils.py` | 3 | Декомпрессия .gz/.Z | bytes, filename | str (UTF-8) |
| `gps_time.py` | 3 | Конвертации времени GPS | datetime | str (YYYYDDD, YYMMDDHR, GPS-неделя) |
| `parsers.py` | 3 | Парсинг SP3 и RINEX CLK | str (текст файла) | list[dict] |
| `detector.py` | 4 | MAD со скользящим окном | list[dict] | list[DetectionResult] |
| `analytics.py` | 4 | Дрейф, шум, индекс здоровья | list[DetectionResult] | dict |
| `ftp_client.py` | 5 | FTP GLONASS-IAC | days_back, already_loaded | Iterator[(fname, text, subdir)] |
| `nasa_client.py` | 5 | HTTPS NASA CDDIS | days_back, already_loaded | Iterator[(fname, text)] |
| `etl.py` | 6 | ETL pipeline + CLI | source, days_back | dict (stats) |
| `app.py` | 7 | Flask factory + API routes | — | Flask app |

## Ключевые функции

### gps_time.py
- `date_to_dir(dt)` → "26079" (YYYYDDD для FTP)
- `file_stem(prefix, dt, slot_h)` → "Stark_26032000"
- `utc_to_gps_week(dt)` → (week, dow) для NASA
- `slots_to_fetch(days_back)` → [(date, slot_h), ...]

### parsers.py
- `parse_file(content, filename)` → list[dict] (диспетчер)
- `parse_rinex_clk(content)` → list[dict] (обрабатывает D-нотацию, CRLF)
- `parse_sp3(content)` → list[dict] (мкс → нс)

### detector.py
- `detect_outliers(timeseries, threshold, window_size)` → list[DetectionResult]
