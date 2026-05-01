"""
ETL pipeline: FTP → parse → SQLite.

Запуск:
    python -m gnss_clock.etl --days 7
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone

_utcnow = lambda: datetime.now(timezone.utc).replace(tzinfo=None)

from . import config
from .parsers import parse_file
from .ftp_client import iter_new_files as ftp_iter

logger = logging.getLogger(__name__)



def _get_app():
    from flask import current_app, Flask
    if current_app:
        return current_app._get_current_object()
        
    from . import config
    from .models import db
    from sqlalchemy import inspect as sa_inspect

    app = Flask("etl_worker")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=config.DATABASE_URI,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    if hasattr(config, "SQLALCHEMY_ENGINE_OPTIONS"):
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = config.SQLALCHEMY_ENGINE_OPTIONS
        
    db.init_app(app)
    with app.app_context():
        db.create_all()
        inspector = sa_inspect(db.engine)
        if "sat_clock" in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns("sat_clock")]
            if "product_type" not in cols:
                try:
                    db.session.execute(db.text("ALTER TABLE sat_clock ADD COLUMN product_type VARCHAR(10)"))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
        
        if "etl_log" in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns("etl_log")]
            if "processed_sats" not in cols:
                try:
                    db.session.execute(db.text("ALTER TABLE etl_log ADD COLUMN processed_sats TEXT"))
                    db.session.commit()
                except Exception:
                    db.session.rollback()

        if "satellite_meta" in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns("satellite_meta")]
            if "sat_num" not in cols:
                try:
                    db.session.execute(db.text("ALTER TABLE satellite_meta ADD COLUMN sat_num VARCHAR(10)"))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
    return app


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
        try:
            db.session.bulk_insert_mappings(SatClock, records)
            db.session.commit()
            return len(records)
        except Exception:
            db.session.rollback()
            inserted = 0
            for record in records:
                try:
                    db.session.add(SatClock(**record))
                    db.session.commit()
                    inserted += 1
                except Exception:
                    db.session.rollback()
            return inserted


def _purge_old_data(app) -> None:
    from .models import db, SatClock, EtlLog
    cutoff = _utcnow() - timedelta(days=config.ETL_RETAIN_DAYS)
    with app.app_context():
        n1 = SatClock.query.filter(SatClock.epoch < cutoff).delete()
        old_logs = EtlLog.query.order_by(EtlLog.started_at.desc()).offset(200).all()
        for log in old_logs:
            db.session.delete(log)
        db.session.commit()
        if n1:
            logger.info("Purge: %d raw clock records (>%d days)", n1, config.ETL_RETAIN_DAYS)


def run_etl(days_back: int = config.ETL_DAYS_BACK, source: str = "ftp") -> dict:
    from .models import db, EtlLog, SatelliteMeta
    app = _get_app()
    stats = {
        "started_at": _utcnow().isoformat(), "files_processed": 0,
        "records_raw": 0, "records_new": 0, "errors": [], "source": source,
    }
    loaded_files = _already_loaded_files(app)

    if source == "nasa":
        from .nasa_client import iter_new_files as nasa_iter
        file_iterator = ((fname, text, "ultra") for fname, text in nasa_iter(days_back, loaded_files))
        record_source = "nasa"
    else:
        file_iterator = ftp_iter(days_back, loaded_files)
        record_source = "ftp"

    # Собираем все новые файлы в список для сортировки
    all_new_files = list(file_iterator)
    
    # Сортировка: .glo (0) -> .oe (1) -> .hlt (2) -> остальные (.clk, .sp3) (3)
    def file_priority(item):
        fname = item[0].lower()
        if any(fname.endswith(ext) for ext in [".glo", ".gps", ".bds", ".gal", ".qzs"]): return 0
        if fname.endswith(".oe"): return 1
        if fname.endswith(".hlt"): return 2
        return 3
    
    all_new_files.sort(key=file_priority)

    for fname, text, subdir in all_new_files:
        file_key = f"{subdir}/{fname}"
        
        if any(fname.lower().endswith(ext) for ext in [".glo", ".gps", ".bds", ".gal", ".qzs"]):
            from .status_parsers import parse_glo
            records = parse_glo(text)
            stats["files_processed"] += 1
            unique_sats = sorted(list(set(r["sat_id"] for r in records)))
            processed_sats_str = ",".join(unique_sats)
            
            with app.app_context():
                log = EtlLog(ftp_file=file_key, records_raw=len(records), processed_sats=processed_sats_str)
                db.session.add(log)
                for r in records:
                    meta = db.session.get(SatelliteMeta, r['sat_id'])
                    if not meta:
                        db.session.add(SatelliteMeta(**r))
                    else:
                        # Обновляем паспортные данные
                        for k, v in r.items():
                            setattr(meta, k, v)
                log.status = "ok"
                log.finished_at = _utcnow()
                db.session.commit()
            logger.info(f"Loaded meta passport for {len(records)} satellites")
            continue
            
        elif fname.lower().endswith(".oe"):
            from .status_parsers import parse_oe
            records = parse_oe(text)
            stats["files_processed"] += 1
            
            with app.app_context():
                log = EtlLog(ftp_file=file_key, records_raw=len(records))
                db.session.add(log)
                for r in records:
                    meta = db.session.get(SatelliteMeta, r['sat_id'])
                    if meta:
                        meta.orbit_a = r['orbit_a']
                        meta.orbit_e = r['orbit_e']
                        meta.orbit_i = r['orbit_i']
                log.status = "ok"
                log.finished_at = _utcnow()
                db.session.commit()
            logger.info(f"Updated orbital elements from {fname}")
            continue

        elif fname.lower().endswith(".hlt"):
            from .status_parsers import parse_hlt
            from .models import SatelliteStatusHistory
            records = parse_hlt(text)
            stats["files_processed"] += 1
            unique_sats = sorted(list(set(r["sat_id"] for r in records)))
            processed_sats_str = ",".join(unique_sats)

            with app.app_context():
                log = EtlLog(ftp_file=file_key, records_raw=len(records), processed_sats=processed_sats_str)
                db.session.add(log)
                new_hist = 0
                for r in records:
                    # Гарантируем наличие родительской записи в satellite_meta (для Foreign Key)
                    meta = db.session.get(SatelliteMeta, r['sat_id'])
                    if not meta:
                        sys_guess = "GPS" if r['sat_id'].startswith('G') else "GLONASS" if r['sat_id'].startswith('R') else "Other"
                        db.session.add(SatelliteMeta(sat_id=r['sat_id'], system=sys_guess))
                        db.session.flush()

                    exists = SatelliteStatusHistory.query.filter_by(
                        sat_id=r['sat_id'], start_epoch=r['start_epoch'], end_epoch=r['end_epoch']
                    ).first()
                    if not exists:
                        db.session.add(SatelliteStatusHistory(**r))
                        new_hist += 1
                log.records_new = new_hist
                log.status = "ok"
                log.finished_at = _utcnow()
                db.session.commit()
            logger.info(f"Loaded {new_hist} .hlt records")
            continue

        # Standard processing (CLK, SP3)
        records = parse_file(text, fname)
        stats["files_processed"] += 1
        stats["records_raw"] += len(records)

        unique_sats = sorted(list(set(r["sat_id"] for r in records)))
        processed_sats_str = ",".join(unique_sats)

        file_key = f"{subdir}/{fname}"
        product_type = subdir
        for r in records:
            r["source"] = record_source
            r["product_type"] = product_type

        with app.app_context():
            # Также создаем заглушки метаданных для часовых данных, если спутник новый
            for s_id in unique_sats:
                if not db.session.get(SatelliteMeta, s_id):
                    sys_guess = "GPS" if s_id.startswith('G') else "GLONASS" if s_id.startswith('R') else "Other"
                    db.session.add(SatelliteMeta(sat_id=s_id, system=sys_guess))
            db.session.commit()

            log = EtlLog(ftp_file=file_key, records_raw=len(records), processed_sats=processed_sats_str)
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
        logger.warning("Источник '%s': 0 новых файлов", source)

    _purge_old_data(app)
    stats["finished_at"] = _utcnow().isoformat()
    logger.info(
        "ETL завершён [%s]: файлов=%d, raw=%d, new=%d, ошибок=%d",
        source, stats["files_processed"], stats["records_raw"],
        stats["records_new"], len(stats["errors"]),
    )
    return stats


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    p = argparse.ArgumentParser(description="GNSS Clock ETL")
    p.add_argument("--days", type=int, default=config.ETL_DAYS_BACK)
    p.add_argument("--source", choices=["ftp", "nasa"], default="ftp")
    args = p.parse_args()
    stats = run_etl(days_back=args.days, source=args.source)
    if stats["errors"]:
        sys.exit(1)

if __name__ == "__main__":
    main()
