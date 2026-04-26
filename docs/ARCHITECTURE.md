# Архитектура gnss-clock-detector

## Слоистая модель зависимостей

```
[1] config.py       — os.environ + Path (нет импортов из проекта)
[2] models.py       — SQLAlchemy-модели (зависит от [1])
[3] utils.py        — decompress(), общие утилиты (зависит от [1])
[3] gps_time.py     — чистые функции времени (зависит от [1])
[3] parsers.py      — SP3 и RINEX CLK парсеры (зависит от [1])
[4] detector.py     — MAD со скользящим окном (зависит от [1-3])
[4] analytics.py    — метрики стабильности (зависит от [1-3])
[5] ftp_client.py   — FTP-транспорт GLONASS-IAC (зависит от [1-4])
[5] nasa_client.py  — HTTPS-транспорт NASA CDDIS (зависит от [1-4])
[6] etl.py          — оркестрация pipeline (зависит от [1-5])
[7] app.py          — Flask REST API (зависит от [1-6])
```

## Правила (механически проверяются в CI)

1. Модуль слоя N может импортировать только из слоёв ≤ N
2. `import flask` — только в `app.py`
3. Сетевые запросы (ftplib, requests) — только в `ftp_client.py` и `nasa_client.py`
4. Прямые SQL/ORM запросы — только в `etl.py` и `app.py`
5. numpy — только в `detector.py` и `analytics.py`

## Поток данных

```
GLONASS-IAC FTP          NASA CDDIS HTTPS
      ↓                        ↓
  ftp_client.py          nasa_client.py
      ↓                        ↓
      ├────────────────────────┤
      ↓                        ↓
  parsers.py            status_parsers.py
 (bytes → dict)         (.glo, .hlt → dict)
      ↓                        ↓
      └───────────┬────────────┘
                  ↓
               etl.py            (запись в SatClock, SatelliteMeta, EtlLog)
                  ↓
             detector.py         (MAD → SatClockAnomaly)
                  ↓
               app.py            (REST API)
                  ↓
          index / satellite.html  (Chart.js dashboard)
```

## Проверка зависимостей

```bash
python scripts/check_deps.py
```
