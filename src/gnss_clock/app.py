"""
Flask application factory + REST API.

Endpoints:
    GET  /                                         → index.html
    GET  /api/satellites                           → список спутников
    GET  /api/clock-series?sat_id=R01&from=&to=&threshold=3.0&window_size=15 → ряд + аномалии
    GET  /api/etl/status                           → последние 20 запусков ETL
    POST /api/admin/etl                            → запустить ETL вручную (dev)
"""

import os
import threading
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_utcnow = lambda: datetime.now(timezone.utc).replace(tzinfo=None)

from flask import Flask, jsonify, request, send_from_directory
from sqlalchemy import func

from . import config
from .models import db, SatClock, EtlLog
from .detector import detect_outliers


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    static_dir = Path(__file__).parent / "static"
    app = Flask(__name__, static_folder=str(static_dir), static_url_path="/static")

    app.config.update(
        SQLALCHEMY_DATABASE_URI        = config.DATABASE_URI,
        SQLALCHEMY_TRACK_MODIFICATIONS = False,
        SECRET_KEY                     = config.SECRET_KEY,
        SQLALCHEMY_ENGINE_OPTIONS      = config.SQLALCHEMY_ENGINE_OPTIONS,
    )

    db.init_app(app)
    with app.app_context():
        db.create_all()

    _register_routes(app)
    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date_range(args):
    date_from = args.get("from")
    date_to   = args.get("to")
    if not date_from or not date_to:
        return None, None
    try:
        from_dt = datetime.strptime(date_from, "%Y-%m-%d")
        to_dt   = datetime.strptime(date_to,   "%Y-%m-%d") + timedelta(days=1)
        return from_dt, to_dt
    except ValueError:
        return None, None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _register_routes(app: Flask) -> None:

    @app.route("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.route("/api/satellites")
    def get_satellites():
        rows = (
            db.session.query(
                SatClock.sat_id,
                func.count(SatClock.id).label("count"),
                func.max(SatClock.epoch).label("last_epoch"),
            )
            .group_by(SatClock.sat_id)
            .all()
        )
        return jsonify({
            "satellites": [
                {
                    "sat_id":     r.sat_id,
                    "count":      r.count,
                    "last_epoch": r.last_epoch.isoformat() if r.last_epoch else None,
                }
                for r in sorted(rows, key=lambda x: x.sat_id)
            ]
        })

    @app.route("/api/clock-series")
    def clock_series():
        sat_id      = request.args.get("sat_id")
        threshold   = request.args.get("threshold", default=3.0, type=float)
        window_size = request.args.get("window_size", default=15, type=int)
        from_dt, to_dt = _parse_date_range(request.args)

        if not sat_id:
            return jsonify({"error": "sat_id required"}), 400
        if from_dt is None:
            return jsonify({"error": "from/to required (YYYY-MM-DD)"}), 400

        records = (
            SatClock.query
            .filter(
                SatClock.sat_id == sat_id,
                SatClock.epoch  >= from_dt,
                SatClock.epoch  <  to_dt,
            )
            .order_by(SatClock.epoch)
            .all()
        )

        if not records:
            return jsonify({"error": f"No data for {sat_id} in the selected range"}), 404

        timeseries_raw = [
            {"epoch": r.epoch, "clock_bias": r.clock_bias}
            for r in records
        ]

        results = detect_outliers(
            timeseries_raw,
            threshold=threshold,
            window_size=window_size
        )

        return jsonify({
            "sat_id":     sat_id,
            "count":      len(results),
            "anomalies":  sum(1 for r in results if r.is_outlier),
            "threshold":  threshold,
            "window_size": window_size,
            "timeseries": [
                {
                    "epoch":       r.epoch.isoformat(),
                    "clock_bias":  r.clock_bias,
                    "delta_clock": r.delta_clock,
                    "is_outlier":  r.is_outlier,
                    "score":       r.score,
                    "median":      r.median,
                    "mad":         r.mad,
                }
                for r in results
            ],
        })

    @app.route("/api/etl/status")
    def etl_status():
        logs = EtlLog.query.order_by(EtlLog.started_at.desc()).limit(20).all()
        return jsonify({
            "runs": [
                {
                    "id":           l.id,
                    "started_at":   l.started_at.isoformat()  if l.started_at  else None,
                    "finished_at":  l.finished_at.isoformat() if l.finished_at else None,
                    "ftp_file":     l.ftp_file,
                    "records_raw":  l.records_raw,
                    "records_new":  l.records_new,
                    "status":       l.status,
                    "message":      l.message,
                }
                for l in logs
            ]
        })

    # ── Admin: trigger ETL manually ───────────────────────────────────────

    _etl_running = {'status': None, 'progress': 0, 'error': None}

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

    # ── Error handlers ────────────────────────────────────────────────────

    @app.errorhandler(404)
    def not_found(_):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def server_error(_):
        return jsonify({"error": "Server error"}), 500
