"""
Flask application factory + REST API.

Endpoints:
    GET  /                                              → index.html (главный дашборд)
    GET  /satellite/<sat_id>                            → satellite.html (страница КА)
    GET  /api/satellites                                → список спутников с кол-вом записей
    GET  /api/satellites/<sat_id>/meta                  → метаданные КА (из .glo)
    GET  /api/satellites/<sat_id>/history               → история статусов КА (из .hlt)
    GET  /api/satellites/<sat_id>/cache                 → кэш аналитики по дате
    GET  /api/data/<sat_id>?type=&from=&to=&threshold=&window_size=
                                                        → временной ряд + аналитика MAD
    GET  /api/etl/status                                → последние 20 записей лога ETL
    POST /api/admin/etl  body: {"source": "ftp"|"nasa"} → запустить ETL в фоне
    GET  /api/admin/etl/status                          → статус текущего фонового ETL
"""

import os
import threading
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

from flask import Flask, jsonify, request, send_from_directory
from sqlalchemy import func, inspect as sa_inspect

from . import config
from .models import db, SatClock, EtlLog, SatelliteMeta, SatelliteStatusHistory, AnalyticsCache, SatelliteOrbitHistory
from .detector import detect_outliers
from .analytics import calculate_satellite_analytics


def create_app() -> Flask:
    static_dir = Path(__file__).parent / "static"
    app = Flask(__name__, static_folder=str(static_dir), static_url_path="/static")

    app.config.update(
        SQLALCHEMY_DATABASE_URI=config.DATABASE_URI,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SECRET_KEY=config.SECRET_KEY,
        SQLALCHEMY_ENGINE_OPTIONS=config.SQLALCHEMY_ENGINE_OPTIONS,
    )

    db.init_app(app)
    with app.app_context():
        db.create_all()
        # Миграции: добавляем колонки только если их нет
        inspector = sa_inspect(db.engine)
        
        # 1. SatClock migration
        if "sat_clock" in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns("sat_clock")]
            if "product_type" not in cols:
                db.session.execute(db.text("ALTER TABLE sat_clock ADD COLUMN product_type VARCHAR(10)"))
                db.session.commit()
                logger.info("Added 'product_type' column to sat_clock.")

        # 2. EtlLog migration
        if "etl_log" in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns("etl_log")]
            if "processed_sats" not in cols:
                db.session.execute(db.text("ALTER TABLE etl_log ADD COLUMN processed_sats TEXT"))
                db.session.commit()
                logger.info("Added 'processed_sats' column to etl_log.")

        # 3. SatClockAnomaly migration
        if "sat_clock_anomaly" in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns("sat_clock_anomaly")]
            if "detection_method" not in cols:
                db.session.execute(db.text("ALTER TABLE sat_clock_anomaly ADD COLUMN detection_method VARCHAR(10) DEFAULT 'bias'"))
                db.session.execute(db.text("UPDATE sat_clock_anomaly SET detection_method = 'bias' WHERE detection_method IS NULL"))
                db.session.commit()
                logger.info("Added 'detection_method' column to sat_clock_anomaly.")
            
            # Add unique index if it doesn't exist
            # Note: SQLite doesn't support ADD CONSTRAINT, so we use CREATE UNIQUE INDEX
            indexes = [idx["name"] for idx in inspector.get_indexes("sat_clock_anomaly")]
            if "uix_anomaly_sat_epoch_method" not in indexes:
                try:
                    # Drop old index if exists
                    if "uix_anomaly_sat_epoch" in indexes:
                        db.session.execute(db.text("DROP INDEX uix_anomaly_sat_epoch"))
                    
                    db.session.execute(db.text(
                        "CREATE UNIQUE INDEX uix_anomaly_sat_epoch_method ON sat_clock_anomaly(sat_id, epoch, detection_method)"
                    ))
                    db.session.commit()
                    logger.info("Created unique index uix_anomaly_sat_epoch_method.")
                except Exception as e:
                    db.session.rollback()
                    logger.warning(f"Could not update index for sat_clock_anomaly: {e}")

        # 4. SatelliteMeta migration
        if "satellite_meta" in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns("satellite_meta")]
            if "sat_num" not in cols:
                db.session.execute(db.text("ALTER TABLE satellite_meta ADD COLUMN sat_num VARCHAR(10)"))
                db.session.commit()
                logger.info("Added 'sat_num' column to satellite_meta.")
            if "assessment_date" not in cols:
                db.session.execute(db.text("ALTER TABLE satellite_meta ADD COLUMN assessment_date DATE"))
                db.session.commit()
                logger.info("Added 'assessment_date' column to satellite_meta.")
            if "orbit_a" not in cols:
                db.session.execute(db.text("ALTER TABLE satellite_meta ADD COLUMN orbit_a FLOAT"))
                db.session.execute(db.text("ALTER TABLE satellite_meta ADD COLUMN orbit_e FLOAT"))
                db.session.execute(db.text("ALTER TABLE satellite_meta ADD COLUMN orbit_i FLOAT"))
                db.session.commit()
                logger.info("Added orbit columns to satellite_meta.")

        # 5. SatelliteOrbitHistory creation (if db.create_all missed it)
        if "satellite_orbit_history" not in inspector.get_table_names():
            db.create_all()
            logger.info("Created satellite_orbit_history table.")

    _register_routes(app)
    return app


def _parse_date_range(args):
    date_from = args.get("from")
    date_to = args.get("to")
    if not date_from or not date_to:
        return None, None
    try:
        from_dt = datetime.strptime(date_from, "%Y-%m-%d")
        to_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
        return from_dt, to_dt
    except ValueError:
        return None, None


def _register_routes(app: Flask) -> None:

    @app.route("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.route("/api/satellites")
    def get_satellites():
        rows = db.session.query(SatClock.sat_id, func.count(SatClock.id).label("count")).group_by(SatClock.sat_id).all()
        return jsonify({"satellites": [{"sat_id": r.sat_id, "count": r.count} for r in sorted(rows, key=lambda x: x.sat_id)]})

    @app.route("/api/satellites/<string:sat_id>/meta")
    def get_satellite_meta(sat_id: str):
        meta = SatelliteMeta.query.get(sat_id)
        if not meta:
            return jsonify({"error": f"Metadata for {sat_id} not found"}), 404
        return jsonify(meta.as_dict())

    @app.route("/api/satellites/<string:sat_id>/history")
    def get_satellite_history(sat_id: str):
        history = SatelliteStatusHistory.query.filter_by(sat_id=sat_id).order_by(SatelliteStatusHistory.start_epoch.desc()).all()
        return jsonify([h.as_dict() for h in history])

    @app.route("/api/correlation/<string:sat_id>")
    def get_correlation_data(sat_id: str):
        from .detector import detect_outliers
        
        # 1. Получаем все аномалии (используем rapid по умолчанию)
        # На самом деле, лучше взять из SatClock и прогнать MAD прямо здесь для нужного периода
        from_dt, to_dt = _parse_date_range(request.args)
        if not from_dt:
            from_dt = datetime.now() - timedelta(days=30)
            to_dt = datetime.now()

        records = SatClock.query.filter(
            SatClock.sat_id == sat_id,
            SatClock.product_type == 'rapid',
            SatClock.epoch >= from_dt,
            SatClock.epoch < to_dt,
        ).order_by(SatClock.epoch).all()

        if not records:
            return jsonify({"error": "No data"}), 404

        timeseries_raw = [{"epoch": r.epoch, "clock_bias": r.clock_bias} for r in records]
        detection_results = detect_outliers(timeseries_raw)
        anomalies = [r for r in detection_results if r.is_outlier]

        # 2. Для каждой аномалии ищем ближайшее положение на орбите
        correlation = []
        for anom in anomalies:
            # Ближайшая запись в пределах +/- 1 часа
            orbit = SatelliteOrbitHistory.query.filter(
                SatelliteOrbitHistory.sat_id == sat_id,
                SatelliteOrbitHistory.epoch >= anom.epoch - timedelta(hours=1),
                SatelliteOrbitHistory.epoch <= anom.epoch + timedelta(hours=1)
            ).order_by(func.abs(func.julianday(SatelliteOrbitHistory.epoch) - func.julianday(anom.epoch))).first()

            if orbit:
                res = anom.__dict__.copy()
                res.update({
                    "orbit_epoch": orbit.epoch.isoformat(),
                    "a": orbit.a,
                    "e": orbit.e,
                    "i": orbit.i,
                    "mean_anomaly": orbit.mean_anomaly,
                    "altitude": orbit.a - 6371.0
                })
                correlation.append(res)

        return jsonify(correlation)

    @app.route("/api/satellites/<string:sat_id>/cache")
    def get_satellite_cache(sat_id: str):
        from_dt, to_dt = _parse_date_range(request.args)
        query = AnalyticsCache.query.filter_by(sat_id=sat_id)
        if from_dt and to_dt:
            query = query.filter(AnalyticsCache.date >= from_dt.date(), AnalyticsCache.date < to_dt.date())
        cache_records = query.order_by(AnalyticsCache.date.desc()).all()
        return jsonify([c.as_dict() for c in cache_records])

    @app.route("/api/data/<string:sat_id>")
    def get_data(sat_id: str):
        product_type = request.args.get("type", "rapid", type=str)
        threshold = request.args.get("threshold", default=3.0, type=float)
        window_size = request.args.get("window_size", default=15, type=int)
        from_dt, to_dt = _parse_date_range(request.args)

        if not from_dt or not to_dt:
            return jsonify({"error": "Date range ('from', 'to') is required"}), 400

        records = SatClock.query.filter(
            SatClock.sat_id == sat_id,
            SatClock.product_type == product_type,
            SatClock.epoch >= from_dt,
            SatClock.epoch < to_dt,
        ).order_by(SatClock.epoch).all()

        if not records:
            return jsonify({"error": f"No '{product_type}' data for {sat_id} in the selected range"}), 404

        timeseries_raw = [{"epoch": r.epoch, "clock_bias": r.clock_bias} for r in records]
        detection_results = detect_outliers(timeseries_raw, threshold=threshold, window_size=window_size)
        analytics = calculate_satellite_analytics(detection_results)

        return jsonify({
            "data": [r.__dict__ for r in detection_results],
            "analytics": analytics
        })

    @app.route("/api/etl/status")
    def etl_status():
        logs = EtlLog.query.order_by(EtlLog.started_at.desc()).limit(20).all()
        return jsonify({"runs": [l.as_dict() for l in logs]})

    _etl_running = {'status': None, 'error': None}
    @app.route("/api/admin/etl", methods=["POST"])
    def trigger_etl():
        if _etl_running.get('status') == 'running':
            return jsonify({"error": "ETL already running"}), 409

        # Поддержка выбора источника из клиента (ftp или nasa)
        data = request.get_json(silent=True) or {}
        source = data.get("source", "ftp")

        def run_etl_background(src):
            _etl_running['status'] = 'running'
            _etl_running['error'] = None
            try:
                from .etl import run_etl
                stats = run_etl(source=src)
                _etl_running['status'] = 'completed'
                _etl_running['result'] = stats
            except Exception as e:
                _etl_running['status'] = 'failed'
                _etl_running['error'] = str(e)
                logger.error(f"Background ETL failed: {e}", exc_info=True)

        thread = threading.Thread(target=run_etl_background, args=(source,), daemon=True)
        thread.start()
        return jsonify({"status": "started", "message": f"ETL ({source}) started in background"}), 202

    @app.route("/api/admin/etl/status", methods=["GET"])
    def admin_etl_status():
        return jsonify(_etl_running)

    @app.route("/satellite/<string:sat_id>")
    def satellite_page(sat_id: str):
        return send_from_directory(app.static_folder, "satellite.html")

    @app.route("/admin/etl")
    def etl_admin_page():
        return send_from_directory(app.static_folder, "index.html")

    @app.errorhandler(404)
    def not_found(_): return jsonify({"error": "Not found"}), 404
    @app.errorhandler(500)
    def server_error(_): return jsonify({"error": "Server error"}), 500
