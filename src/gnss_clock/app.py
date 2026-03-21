"""
Flask application factory + REST API.

Endpoints:
    GET  /                                    → index.html
    GET  /api/satellites                      → список спутников
    GET  /api/clock-series                    → временной ряд + аномалии
    GET  /api/clock-anomalies                 → только аномалии
    GET  /api/stats/daily                     → суточная сводка
    GET  /api/etl/status                      → последние запуски ETL
    POST /api/admin/etl                       → запустить ETL вручную (dev only)
"""

import os
from datetime import datetime, timedelta, timezone

_utcnow = lambda: datetime.now(timezone.utc).replace(tzinfo=None)
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from sqlalchemy import func

from . import config
from .models import db, SatClock, SatClockAnomaly, EtlLog


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    static_dir = Path(__file__).parent / "static"
    app = Flask(__name__, static_folder=str(static_dir), static_url_path="/static")

    app.config.update(
        SQLALCHEMY_DATABASE_URI        = f"sqlite:///{config.DB_PATH}",
        SQLALCHEMY_TRACK_MODIFICATIONS = False,
        SECRET_KEY                     = config.SECRET_KEY,
    )

    db.init_app(app)

    with app.app_context():
        db.create_all()

    _register_routes(app)
    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date_range(args) -> tuple[datetime, datetime] | tuple[None, None]:
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

    # ── Frontend ──────────────────────────────────────────────────────────

    @app.route("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    # ── Satellites ────────────────────────────────────────────────────────

    @app.route("/api/satellites")
    def get_satellites():
        """GET /api/satellites — список спутников с данными в БД."""
        rows = (
            db.session.query(
                SatClockAnomaly.sat_id,
                func.count(SatClockAnomaly.id).label("count"),
                func.sum(SatClockAnomaly.is_outlier.cast(db.Integer)).label("anomalies"),
                func.max(SatClockAnomaly.epoch).label("last_epoch"),
            )
            .group_by(SatClockAnomaly.sat_id)
            .all()
        )
        return jsonify({
            "satellites": [
                {
                    "sat_id":    r.sat_id,
                    "count":     r.count,
                    "anomalies": r.anomalies or 0,
                    "last_epoch": r.last_epoch.isoformat() if r.last_epoch else None,
                }
                for r in sorted(rows, key=lambda x: x.sat_id)
            ]
        })

    # ── Clock series ──────────────────────────────────────────────────────

    @app.route("/api/clock-series")
    def clock_series():
        """
        GET /api/clock-series?sat_id=R01&from=YYYY-MM-DD&to=YYYY-MM-DD
        Полный временной ряд с флагами аномалий.
        """
        sat_id = request.args.get("sat_id")
        from_dt, to_dt = _parse_date_range(request.args)

        if not sat_id:
            return jsonify({"error": "sat_id required"}), 400
        if from_dt is None:
            return jsonify({"error": "from/to required (YYYY-MM-DD)"}), 400

        records = (
            SatClockAnomaly.query
            .filter(
                SatClockAnomaly.sat_id == sat_id,
                SatClockAnomaly.epoch  >= from_dt,
                SatClockAnomaly.epoch  <  to_dt,
            )
            .order_by(SatClockAnomaly.epoch)
            .all()
        )

        if not records:
            return jsonify({"error": f"No data for {sat_id}"}), 404

        first = records[0]
        return jsonify({
            "sat_id":     sat_id,
            "count":      len(records),
            "anomalies":  sum(1 for r in records if r.is_outlier),
            "median":     first.median,
            "mad":        first.mad,
            "timeseries": [
                {
                    "epoch":       r.epoch.isoformat(),
                    "clock_bias":  r.clock_bias,
                    "delta_clock": r.delta_clock,
                    "is_outlier":  r.is_outlier,
                    "score":       r.score,
                }
                for r in records
            ],
        })

    # ── Anomalies only ────────────────────────────────────────────────────

    @app.route("/api/clock-anomalies")
    def clock_anomalies():
        """GET /api/clock-anomalies?sat_id=R01&from=...&to=... — только выбросы."""
        sat_id = request.args.get("sat_id")
        from_dt, to_dt = _parse_date_range(request.args)

        if not sat_id:
            return jsonify({"error": "sat_id required"}), 400
        if from_dt is None:
            return jsonify({"error": "from/to required"}), 400

        records = (
            SatClockAnomaly.query
            .filter(
                SatClockAnomaly.sat_id     == sat_id,
                SatClockAnomaly.epoch      >= from_dt,
                SatClockAnomaly.epoch      <  to_dt,
                SatClockAnomaly.is_outlier == True,
            )
            .order_by(SatClockAnomaly.epoch)
            .all()
        )
        return jsonify({
            "sat_id":    sat_id,
            "count":     len(records),
            "anomalies": [
                {
                    "epoch":      r.epoch.isoformat(),
                    "clock_bias": r.clock_bias,
                    "score":      r.score,
                }
                for r in records
            ],
        })

    # ── Daily stats ───────────────────────────────────────────────────────

    @app.route("/api/stats/daily")
    def stats_daily():
        """GET /api/stats/daily?date=YYYY-MM-DD — сводка по всем спутникам за день."""
        date_str = request.args.get("date", _utcnow().strftime("%Y-%m-%d"))
        try:
            target = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "invalid date"}), 400

        next_d = target + timedelta(days=1)
        rows = (
            db.session.query(
                SatClockAnomaly.sat_id,
                func.count(SatClockAnomaly.id).label("total"),
                func.sum(SatClockAnomaly.is_outlier.cast(db.Integer)).label("anomalies"),
            )
            .filter(SatClockAnomaly.epoch >= target, SatClockAnomaly.epoch < next_d)
            .group_by(SatClockAnomaly.sat_id)
            .all()
        )
        return jsonify({
            "date": date_str,
            "stats": [
                {
                    "sat_id":       r.sat_id,
                    "total":        r.total,
                    "anomalies":    r.anomalies or 0,
                    "anomaly_rate": round((r.anomalies or 0) / r.total * 100, 2) if r.total else 0,
                }
                for r in sorted(rows, key=lambda x: x.sat_id)
            ],
        })

    # ── ETL status ────────────────────────────────────────────────────────

    @app.route("/api/etl/status")
    def etl_status():
        """GET /api/etl/status — последние 20 запусков ETL."""
        logs = EtlLog.query.order_by(EtlLog.started_at.desc()).limit(20).all()
        return jsonify({
            "runs": [
                {
                    "id":          l.id,
                    "started_at":  l.started_at.isoformat() if l.started_at else None,
                    "finished_at": l.finished_at.isoformat() if l.finished_at else None,
                    "ftp_file":    l.ftp_file,
                    "records_raw": l.records_raw,
                    "records_new": l.records_new,
                    "status":      l.status,
                    "message":     l.message,
                }
                for l in logs
            ]
        })

    # ── Admin: trigger ETL manually ───────────────────────────────────────

    @app.route("/api/admin/etl", methods=["POST"])
    def trigger_etl():
        """
        POST /api/admin/etl  {"test": true}
        Только для локальной разработки (не защищён паролем!).
        """
        if not config.FLASK_DEBUG:
            return jsonify({"error": "Available only in debug mode"}), 403

        body = request.get_json(silent=True) or {}
        use_test = body.get("test", False)

        from .etl import run_etl
        stats = run_etl(use_test_data=use_test)
        return jsonify(stats)

    # ── Error handlers ────────────────────────────────────────────────────

    @app.errorhandler(404)
    def not_found(_):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def server_error(_):
        return jsonify({"error": "Server error"}), 500
