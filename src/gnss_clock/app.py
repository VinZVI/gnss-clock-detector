"""
Flask application factory + REST API.

Endpoints:
    GET  /                                         → index.html
    GET  /api/satellites                           → список спутников
    GET  /api/data/{sat_id}?type=...&threshold=...&window=... → данные + аналитика
    GET  /api/etl/status                           → последние 20 запусков ETL
    POST /api/admin/etl                            → запустить ETL вручную (dev)
"""

import os
import threading
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

from flask import Flask, jsonify, request, send_from_directory
from sqlalchemy import func

from . import config
from .models import db, SatClock, EtlLog
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
        # Миграция: добавляем product_type, если еще не существует
        try:
            db.session.execute(db.text("ALTER TABLE sat_clock ADD COLUMN product_type VARCHAR(10)"))
            db.session.commit()
            logger.info("Added 'product_type' column to sat_clock table.")
        except Exception:
            db.session.rollback()
            logger.debug("'product_type' column already exists.")

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

        def run_etl_background():
            _etl_running['status'] = 'running'
            _etl_running['error'] = None
            try:
                from .etl import run_etl
                stats = run_etl()
                _etl_running['status'] = 'completed'
                _etl_running['result'] = stats
            except Exception as e:
                _etl_running['status'] = 'failed'
                _etl_running['error'] = str(e)
                logger.error(f"Background ETL failed: {e}", exc_info=True)

        thread = threading.Thread(target=run_etl_background, daemon=True)
        thread.start()
        return jsonify({"status": "started", "message": "ETL started in background"}), 202

    @app.route("/api/admin/etl/status", methods=["GET"])
    def admin_etl_status():
        return jsonify(_etl_running)

    @app.errorhandler(404)
    def not_found(_): return jsonify({"error": "Not found"}), 404
    @app.errorhandler(500)
    def server_error(_): return jsonify({"error": "Server error"}), 500
