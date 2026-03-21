"""
ETL pipeline: FTP → parse → SQLite → MAD detection.

Запуск:
    python -m gnss_clock.etl              # FTP, последние 3 дня
    python -m gnss_clock.etl --days 7     # FTP, 7 дней
    python -m gnss_clock.etl --test       # синтетические данные (без FTP)
    python -m gnss_clock.etl --no-anomaly # только загрузка, без детекции

PythonAnywhere scheduled task (hourly):
    /home/<user>/.venv/bin/python -m gnss_clock.etl
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone

_utcnow = lambda: datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC для SQLite

import numpy as np

from . import config
from .detector import detect_outliers
from .ftp_client import iter_new_files
from .parsers import parse_file

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bootstrap Flask app (нужен контекст для ORM)
# ---------------------------------------------------------------------------

def _get_app():
    """Импортируем app здесь, чтобы избежать circular imports."""
    from .app import create_app
    return create_app()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _already_loaded_files(app) -> set[str]:
    """Возвращает множество имён файлов, уже обработанных ETL."""
    from .models import EtlLog
    with app.app_context():
        rows = EtlLog.query.filter(
            EtlLog.status == "ok",
            EtlLog.ftp_file.isnot(None),
        ).with_entities(EtlLog.ftp_file).all()
        return {r.ftp_file for r in rows}


def _load_clocks(app, records: list[dict]) -> int:
    """
    Batch-insert новых raw clock-записей.
    Дубли (по sat_id + epoch + source) пропускаются через INSERT OR IGNORE.
    Возвращает число реально добавленных строк.
    """
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from .models import db, SatClock

    if not records:
        return 0

    with app.app_context():
        stmt = sqlite_insert(SatClock).values(records)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["sat_id", "epoch", "source"]
        )
        result = db.session.execute(stmt)
        db.session.commit()
        return result.rowcount


def _process_anomalies(app, since: datetime) -> int:
    """
    Пересчитывает аномалии за период [since, now].
    Bulk-delete старых результатов за период + bulk-insert новых.
    Возвращает суммарное число аномалий.
    """
    from .models import db, SatClock, SatClockAnomaly

    total_anomalies = 0

    with app.app_context():
        sat_ids: list[str] = [
            r[0] for r in
            db.session.query(SatClock.sat_id).distinct()
            .filter(SatClock.epoch >= since).all()
        ]
        logger.info("Детекция аномалий: %d спутников", len(sat_ids))

        for sat_id in sat_ids:
            raw = SatClock.query.filter(
                SatClock.sat_id == sat_id,
                SatClock.epoch  >= since,
            ).order_by(SatClock.epoch).all()

            if len(raw) < 3:
                continue

            ts = [{"epoch": r.epoch, "clock_bias": r.clock_bias} for r in raw]
            results = detect_outliers(ts, threshold=config.MAD_THRESHOLD)

            # Удаляем старые аномалии за период
            SatClockAnomaly.query.filter(
                SatClockAnomaly.sat_id == sat_id,
                SatClockAnomaly.epoch  >= since,
            ).delete(synchronize_session=False)

            # Вставляем новые
            for r in results:
                db.session.add(SatClockAnomaly(
                    sat_id      = sat_id,
                    epoch       = r.epoch,
                    clock_bias  = r.clock_bias,
                    delta_clock = r.delta_clock,
                    is_outlier  = r.is_outlier,
                    score       = r.score,
                    median      = r.median,
                    mad         = r.mad,
                ))

            db.session.commit()

            n_out = sum(1 for r in results if r.is_outlier)
            total_anomalies += n_out
            logger.info(
                "  %s: %d точек, %d аномалий (MAD=%.2f нс)",
                sat_id, len(results), n_out,
                results[0].mad if results else 0,
            )

    return total_anomalies


def _purge_old_data(app) -> None:
    """Удаляет данные старше config.ETL_RETAIN_DAYS из обеих таблиц."""
    from .models import db, SatClock, SatClockAnomaly, EtlLog

    cutoff = _utcnow() - timedelta(days=config.ETL_RETAIN_DAYS)
    with app.app_context():
        n1 = SatClock.query.filter(SatClock.epoch < cutoff).delete()
        n2 = SatClockAnomaly.query.filter(SatClockAnomaly.epoch < cutoff).delete()
        # Держим только последние 200 ETL-логов
        old_logs = (
            EtlLog.query
            .order_by(EtlLog.started_at.desc())
            .offset(200)
            .all()
        )
        for log in old_logs:
            db.session.delete(log)
        db.session.commit()
        if n1 or n2:
            logger.info("Purge: удалено %d raw + %d anomaly (старше %d дней)", n1, n2, config.ETL_RETAIN_DAYS)


# ---------------------------------------------------------------------------
# Тестовые данные
# ---------------------------------------------------------------------------

def _generate_test_data() -> list[dict]:
    """Синтетика для локальной разработки (без FTP)."""
    rng = np.random.default_rng(seed=42)
    now = _utcnow().replace(minute=0, second=0, microsecond=0)
    records = []

    for sat in ["R01", "R02", "R03", "R04", "G01", "G02", "G03", "E01"]:
        base = 1_000.0 + int(sat[1:]) * 10
        for h in range(0, 7 * 24, 6):   # каждые 6 часов, 7 дней
            epoch = now - timedelta(hours=h)
            outlier = rng.random() < 0.05
            bias = base + (rng.normal(0, 500) if outlier else rng.normal(0, 50))
            records.append({
                "sat_id":     sat,
                "epoch":      epoch,
                "clock_bias": float(bias),
                "source":     "test",
            })

    logger.info("Тест: сгенерировано %d записей", len(records))
    return records


# ---------------------------------------------------------------------------
# Главный pipeline
# ---------------------------------------------------------------------------

def run_etl(
    days_back: int = config.ETL_DAYS_BACK,
    use_test_data: bool = False,
    skip_anomaly: bool = False,
) -> dict:
    """
    Запускает полный ETL и возвращает словарь со статистикой.
    Вызывается как из CLI, так и из Flask-эндпоинта /api/admin/etl.
    """
    from .models import db, EtlLog

    app = _get_app()
    stats = {
        "started_at": _utcnow().isoformat(),
        "files_processed": 0,
        "records_raw": 0,
        "records_new": 0,
        "anomalies": 0,
        "errors": [],
    }

    # --- 1. Загрузка данных ---
    if use_test_data:
        records = _generate_test_data()
        stats["files_processed"] = 1
        stats["records_raw"] = len(records)
        with app.app_context():
            log = EtlLog(ftp_file="test-data", records_raw=len(records))
            db.session.add(log)
            db.session.commit()
            new_count = _load_clocks(app, records)
            log.records_new = new_count
            log.status = "ok"
            log.finished_at = _utcnow()
            db.session.commit()
        stats["records_new"] = new_count
    else:
        loaded_files = _already_loaded_files(app)

        for fname, text in iter_new_files(days_back=days_back, already_loaded=loaded_files):
            records = parse_file(text, fname)
            stats["files_processed"] += 1
            stats["records_raw"] += len(records)

            with app.app_context():
                log = EtlLog(ftp_file=fname, records_raw=len(records))
                db.session.add(log)
                db.session.commit()

                try:
                    new_count = _load_clocks(app, records)
                    log.records_new = new_count
                    log.status = "ok"
                    stats["records_new"] += new_count
                except Exception as exc:
                    log.status = "error"
                    log.message = str(exc)
                    stats["errors"].append(f"{fname}: {exc}")
                    logger.exception("Ошибка загрузки %s", fname)
                finally:
                    log.finished_at = _utcnow()
                    db.session.commit()

        if stats["files_processed"] == 0:
            logger.warning("FTP: 0 новых файлов — данные актуальны или FTP недоступен")

    # --- 2. Детекция аномалий ---
    if not skip_anomaly and stats["records_new"] > 0:
        since = _utcnow() - timedelta(days=max(days_back, 2))
        stats["anomalies"] = _process_anomalies(app, since)

    # --- 3. Очистка старых данных ---
    _purge_old_data(app)

    stats["finished_at"] = _utcnow().isoformat()
    logger.info(
        "ETL завершён: файлов=%d, raw=%d, new=%d, аномалий=%d, ошибок=%d",
        stats["files_processed"],
        stats["records_raw"],
        stats["records_new"],
        stats["anomalies"],
        len(stats["errors"]),
    )
    return stats


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    p = argparse.ArgumentParser(description="GNSS Clock ETL — glonass-iac.ru")
    p.add_argument("--days",       type=int,  default=config.ETL_DAYS_BACK,
                   help="Дней назад для загрузки с FTP")
    p.add_argument("--test",       action="store_true",
                   help="Синтетические данные (без FTP)")
    p.add_argument("--no-anomaly", dest="no_anomaly", action="store_true",
                   help="Пропустить расчёт аномалий")
    args = p.parse_args()

    stats = run_etl(
        days_back     = args.days,
        use_test_data = args.test,
        skip_anomaly  = args.no_anomaly,
    )

    if stats["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
