"""
ETL pipeline: FTP / NASA CDDIS → parse → SQLite.

Запуск:
    python -m gnss_clock.etl --days 7
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone

_utcnow = lambda: datetime.now(timezone.utc).replace(tzinfo=None)

import numpy as np

from . import config
from .parsers import parse_file

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bootstrap Flask app
# ---------------------------------------------------------------------------

def _get_app():
    from .app import create_app
    return create_app()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _already_loaded_files(app) -> set[str]:
    from .models import EtlLog
    with app.app_context():
        rows = EtlLog.query.filter(
            EtlLog.status == "ok",
            EtlLog.ftp_file.isnot(None),
        ).with_entities(EtlLog.ftp_file).all()
        return {r.ftp_file for r in rows}


def _load_clocks(app, records: list[dict]) -> int:
    from .models import db, SatClock

    if not records:
        return 0

    with app.app_context():
        # Используем bulk_insert_mappings для эффективности
        # и обрабатываем конфликты на уровне БД (ON CONFLICT DO NOTHING)
        try:
            db.session.bulk_insert_mappings(SatClock, records)
            db.session.commit()
            return len(records)
        except Exception:
            db.session.rollback()
            # Fallback для баз, не поддерживающих bulk insert с конфликтами
            inserted = 0
            for record in records:
                try:
                    db.session.add(SatClock(**record))
                    db.session.commit()
                    inserted += 1
                except:
                    db.session.rollback()
            return inserted


def _purge_old_data(app) -> None:
    from .models import db, SatClock, EtlLog

    cutoff = _utcnow() - timedelta(days=config.ETL_RETAIN_DAYS)
    with app.app_context():
        # Удаляем только сырые данные. Таблица аномалий больше не используется.
        n1 = SatClock.query.filter(SatClock.epoch < cutoff).delete()
        
        # Очищаем старые логи ETL
        old_logs = (
            EtlLog.query.order_by(EtlLog.started_at.desc()).offset(200).all()
        )
        for log in old_logs:
            db.session.delete(log)
            
        db.session.commit()
        if n1:
            logger.info("Purge: %d raw clock records (>%d days)", n1, config.ETL_RETAIN_DAYS)


# ---------------------------------------------------------------------------
# Итератор файлов с учётом источника данных
# ---------------------------------------------------------------------------

def _iter_files(source: str, days_back: int, already_loaded: set[str]):
    from .ftp_client  import iter_new_files as ftp_iter
    from .nasa_client import iter_new_files as nasa_iter

    def _labeled(it, label):
        for fname, text in it:
            yield fname, text, label

    if source == "ftp":
        yield from _labeled(ftp_iter(days_back, already_loaded), "ftp")
    elif source == "nasa":
        yield from _labeled(nasa_iter(days_back, already_loaded), "nasa")
    elif source == "auto":
        ftp_count = 0
        for item in _labeled(ftp_iter(days_back, already_loaded), "ftp"):
            ftp_count += 1
            yield item
        if ftp_count == 0:
            logger.info("FTP: нет новых файлов — пробуем NASA CDDIS")
            yield from _labeled(nasa_iter(days_back, already_loaded), "nasa")
    else:
        logger.error("Неизвестный источник данных: %s", source)


# ---------------------------------------------------------------------------
# Главный pipeline
# ---------------------------------------------------------------------------

def run_etl(
    days_back: int = config.ETL_DAYS_BACK,
    source: str = config.DATA_SOURCE,
) -> dict:
    from .models import db, EtlLog

    app = _get_app()
    stats = {
        "started_at":      _utcnow().isoformat(),
        "source":          source,
        "files_processed": 0,
        "records_raw":     0,
        "records_new":     0,
        "errors":          [],
    }

    loaded_files = _already_loaded_files(app)

    for fname, text, src_label in _iter_files(source, days_back, loaded_files):
        records = parse_file(text, fname)
        stats["files_processed"] += 1
        stats["records_raw"]     += len(records)

        for r in records:
            r["source"] = src_label

        with app.app_context():
            log = EtlLog(ftp_file=fname, data_source=src_label, records_raw=len(records))
            db.session.add(log)
            db.session.commit()
            try:
                new_count       = _load_clocks(app, records)
                log.records_new = new_count
                log.status      = "ok"
                stats["records_new"] += new_count
            except Exception as exc:
                log.status  = "error"
                log.message = str(exc)
                stats["errors"].append(f"{fname}: {exc}")
                logger.exception("Ошибка загрузки %s", fname)
            finally:
                log.finished_at = _utcnow()
                db.session.commit()

    if stats["files_processed"] == 0:
        logger.warning("Источник '%s': 0 новых файлов", source)

    # Очистка старых данных
    _purge_old_data(app)

    stats["finished_at"] = _utcnow().isoformat()
    logger.info(
        "ETL завершён [%s]: файлов=%d, raw=%d, new=%d, ошибок=%d",
        stats["source"],
        stats["files_processed"], stats["records_raw"],
        stats["records_new"], len(stats["errors"]),
    )
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    p = argparse.ArgumentParser(description="GNSS Clock ETL")
    p.add_argument("--source", default=config.DATA_SOURCE,
                   choices=["ftp", "nasa", "auto"],
                   help="Источник данных")
    p.add_argument("--days", type=int, default=config.ETL_DAYS_BACK)
    args = p.parse_args()

    stats = run_etl(
        days_back=args.days,
        source=args.source,
    )
    if stats["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
