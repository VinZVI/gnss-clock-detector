"""
Flask application factory + REST API.

Endpoints:
    GET  /                                         → index.html
    GET  /api/satellites                           → список спутников
    GET  /api/clock-series?sat_id=R01&from=&to=   → ряд + аномалии
    GET  /api/clock-anomalies?sat_id=R01&from=&to= → только выбросы
    GET  /api/stats/daily?date=YYYY-MM-DD          → суточная сводка
    GET  /api/etl/status                           → последние 20 запусков ETL
    GET  /api/sources/status                       → статус источников данных
    POST /api/admin/etl                            → запустить ETL вручную (dev)
"""

import os
import threading
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Module-level logger for use during app initialization
logger = logging.getLogger(__name__)

_utcnow = lambda: datetime.now(timezone.utc).replace(tzinfo=None)

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
        SQLALCHEMY_DATABASE_URI        = config.DATABASE_URI,
        SQLALCHEMY_TRACK_MODIFICATIONS = False,
        SECRET_KEY                     = config.SECRET_KEY,
        SQLALCHEMY_ENGINE_OPTIONS      = config.SQLALCHEMY_ENGINE_OPTIONS,
    )

    db.init_app(app)
    with app.app_context():
        db.create_all()
        
        # Добавляем колонку detection_method если БД была создана раньше
        try:
            db.session.execute(
                db.text("ALTER TABLE sat_clock_anomaly ADD COLUMN detection_method VARCHAR(10) DEFAULT 'bias'")
            )
            db.session.commit()
            logger.info("Added detection_method column")
        except Exception as e:
            db.session.rollback()  # CRITICAL: Reset transaction state
            logger.debug(f"detection_method column already exists: {e}")
        
        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Удаляем старый unique constraint принудительно
        # Это нужно для Render.com где миграция могла не сработать
        try:
            # Проверяем существование старого индекса/констрейнта
            result = db.session.execute(
                db.text("SELECT 1 FROM pg_indexes WHERE indexname = 'uix_anomaly_sat_epoch'")
            ).first()
            if result:
                logger.info("Found old constraint uix_anomaly_sat_epoch - dropping it")
                # Сначала удаляем констрейнт (не индекс)
                db.session.execute(db.text("ALTER TABLE sat_clock_anomaly DROP CONSTRAINT IF EXISTS uix_anomaly_sat_epoch"))
                db.session.commit()
                logger.info("✅ Old constraint dropped successfully")
        except Exception as e:
            db.session.rollback()  # CRITICAL: Reset transaction state
            logger.warning(f"Could not check/drop old constraint: {e}")
        
        # Обновляем unique constraint - удаляем старый и создаём новый
        # Try PostgreSQL first, then SQLite
        try:
            # PostgreSQL: Drop old constraint (double-check)
            db.session.execute(db.text("ALTER TABLE sat_clock_anomaly DROP CONSTRAINT IF EXISTS uix_anomaly_sat_epoch"))
            db.session.commit()
            logger.info("Dropped old constraint uix_anomaly_sat_epoch")
        except Exception as e:
            db.session.rollback()  # CRITICAL: Reset transaction state
            # SQLite doesn't support DROP CONSTRAINT IF EXISTS
            try:
                db.session.execute(db.text('DROP INDEX IF EXISTS "uix_anomaly_sat_epoch"'))
                db.session.commit()
                logger.info("Dropped old index uix_anomaly_sat_epoch (SQLite)")
            except Exception:
                db.session.rollback()
                pass  # Индекс уже удалён или не существует
        
        # Создаём новый unique constraint с detection_method
        try:
            # PostgreSQL syntax
            db.session.execute(
                db.text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uix_anomaly_sat_epoch_method "
                    "ON sat_clock_anomaly(sat_id, epoch, detection_method)"
                )
            )
            db.session.commit()
            logger.info("Created new index uix_anomaly_sat_epoch_method")
        except Exception as e:
            db.session.rollback()  # CRITICAL: Reset transaction state
            try:
                # SQLite syntax
                db.session.execute(
                    db.text(
                        'CREATE UNIQUE INDEX IF NOT EXISTS "uix_anomaly_sat_epoch_method" '
                        'ON sat_clock_anomaly(sat_id, epoch, detection_method)'
                    )
                )
                db.session.commit()
                logger.info("Created new index uix_anomaly_sat_epoch_method (SQLite)")
            except Exception:
                db.session.rollback()
                pass  # Индекс уже существует

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

    # ── Satellites ────────────────────────────────────────────────────────

    @app.route("/api/satellites")
    def get_satellites():
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
                    "sat_id":     r.sat_id,
                    "count":      r.count,
                    "anomalies":  r.anomalies or 0,
                    "last_epoch": r.last_epoch.isoformat() if r.last_epoch else None,
                }
                for r in sorted(rows, key=lambda x: x.sat_id)
            ]
        })

    # ── Clock series ──────────────────────────────────────────────────────

    @app.route("/api/clock-series")
    def clock_series():
        sat_id = request.args.get("sat_id")
        method = request.args.get("method", "bias")  # 'bias' or 'delta'
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
            "method":     method,
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
                {"epoch": r.epoch.isoformat(), "clock_bias": r.clock_bias, "score": r.score}
                for r in records
            ],
        })

    # ── Daily stats ───────────────────────────────────────────────────────

    @app.route("/api/stats/daily")
    def stats_daily():
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
        logs = EtlLog.query.order_by(EtlLog.started_at.desc()).limit(20).all()
        return jsonify({
            "runs": [
                {
                    "id":           l.id,
                    "started_at":   l.started_at.isoformat()  if l.started_at  else None,
                    "finished_at":  l.finished_at.isoformat() if l.finished_at else None,
                    "ftp_file":     l.ftp_file,
                    "data_source":  getattr(l, "data_source", "ftp"),
                    "records_raw":  l.records_raw,
                    "records_new":  l.records_new,
                    "status":       l.status,
                    "message":      l.message,
                }
                for l in logs
            ]
        })

    # ── Sources status ────────────────────────────────────────────────────

    @app.route("/api/sources/status")
    def sources_status():
        """
        GET /api/sources/status
        Возвращает статус всех источников данных и конфигурацию.
        """
        # Статистика по источникам из EtlLog
        source_stats = {}
        try:
            rows = (
                db.session.query(
                    EtlLog.data_source,
                    func.count(EtlLog.id).label("runs"),
                    func.sum(EtlLog.records_new).label("records"),
                    func.max(EtlLog.started_at).label("last_run"),
                )
                .filter(EtlLog.status == "ok")
                .group_by(EtlLog.data_source)
                .all()
            )
            for r in rows:
                source_stats[r.data_source or "ftp"] = {
                    "runs":     r.runs,
                    "records":  int(r.records or 0),
                    "last_run": r.last_run.isoformat() if r.last_run else None,
                }
        except Exception:
            pass

        return jsonify({
            "active_source":    config.DATA_SOURCE,
            "nasa_configured":  bool(config.NASA_USER and config.NASA_PASS),
            "nasa_product":     config.NASA_PRODUCT,
            "ftp_host":         config.FTP_HOST,
            "retain_days":      config.ETL_RETAIN_DAYS,
            "mad_threshold":    config.MAD_THRESHOLD,
            "source_stats":     source_stats,
        })

    # ── NASA credentials check ────────────────────────────────────────────

    @app.route("/api/sources/nasa/check")
    def nasa_check():
        """GET /api/sources/nasa/check — проверить доступность NASA CDDIS."""
        from .nasa_client import check_credentials
        result = check_credentials()
        return jsonify(result), (200 if result["ok"] else 503)

    # ── Admin: trigger ETL manually ───────────────────────────────────────

    # Global state for background ETL
    # Global state for background jobs
    _etl_running = {'status': None, 'progress': 0, 'error': None}
    _recalc_running = {'status': None, 'progress': 0, 'error': None, 'result': None}

    @app.route("/api/admin/etl", methods=["POST"])
    def trigger_etl():
        # Allow in production if SECRET_KEY is set (Render.com)
        # Only block if explicitly disabled
        if os.environ.get("GNSS_DISABLE_ADMIN_ETL", "").lower() == "true":
            return jsonify({"error": "Admin ETL endpoint disabled"}), 403

        body       = request.get_json(silent=True) or {}
        use_test   = body.get("test",   False)
        source     = body.get("source", config.DATA_SOURCE)
        days       = int(body.get("days", 3))

        # Check if already running
        if _etl_running.get('status') == 'running':
            return jsonify({"error": "ETL already running", "progress": _etl_running.get('progress', 0)}), 409

        # Run ETL in background thread to avoid timeout
        def run_etl_background():
            _etl_running['status'] = 'running'
            _etl_running['progress'] = 0
            _etl_running['error'] = None
            
            try:
                from .etl import run_etl
                stats = run_etl(use_test_data=use_test, source=source, days_back=days)
                _etl_running['status'] = 'completed'
                _etl_running['progress'] = 100
                _etl_running['result'] = stats
            except Exception as e:
                _etl_running['status'] = 'failed'
                _etl_running['error'] = str(e)
                _etl_running['details'] = repr(e)
                logger = logging.getLogger(__name__)
                logger.error(f"Background ETL failed: {e}", exc_info=True)

        # Start background thread
        thread = threading.Thread(target=run_etl_background, daemon=True)
        thread.start()

        return jsonify({
            "status": "started",
            "message": "ETL started in background",
            "source": source,
            "days": days
        }), 202

    @app.route("/api/admin/etl/status", methods=["GET"])
    def admin_etl_status():
        """Get status of background ETL job"""
        return jsonify(_etl_running)

    @app.route("/api/admin/recalculate-anomalies", methods=["POST"])
    def recalculate_anomalies():
        """Start background recalculation of anomalies for all satellites"""
        if os.environ.get("GNSS_DISABLE_ADMIN_ETL", "").lower() == "true":
            return jsonify({"error": "Admin endpoint disabled"}), 403
        
        # Check if already running
        if _recalc_running.get('status') == 'running':
            return jsonify({"error": "Recalculation already running"}), 409
        
        # Reset status
        _recalc_running['status'] = 'starting'
        _recalc_running['progress'] = 0
        _recalc_running['error'] = None
        _recalc_running['result'] = None
        
        def run_recalc_background():
            # Create application context for background thread
            with app.app_context():
                _recalc_running['status'] = 'running'
                try:
                    from .models import SatClock, SatClockAnomaly, db
                    from .detector import detect_outliers
                    from datetime import datetime, timezone
                    
                    # Get all unique satellite IDs
                    sat_ids = [r[0] for r in db.session.query(SatClock.sat_id).distinct().all()]
                    total_sats = len(sat_ids)
                    
                    total_processed = 0
                    total_bias = 0
                    total_delta = 0
                    
                    for idx, sat_id in enumerate(sat_ids):
                        # Update progress
                        _recalc_running['progress'] = int((idx / total_sats) * 100) if total_sats > 0 else 0
                        
                        # Get all clock data for this satellite
                        clocks = (
                            SatClock.query
                            .filter(SatClock.sat_id == sat_id)
                            .order_by(SatClock.epoch)
                            .all()
                        )
                        
                        if not clocks:
                            continue
                        
                        # Prepare timeseries for detection
                        timeseries = [
                            {"epoch": c.epoch, "clock_bias": c.clock_bias}
                            for c in clocks
                        ]
                        
                        # Detect with bias method
                        results_bias = detect_outliers(timeseries, threshold=3.0, method='bias')
                        
                        # Detect with delta method
                        results_delta = detect_outliers(timeseries, threshold=3.0, method='delta')
                        
                        # Save bias method results
                        for r in results_bias:
                            try:
                                existing = SatClockAnomaly.query.filter_by(
                                    sat_id=sat_id,
                                    epoch=r.epoch,
                                    detection_method='bias'
                                ).first()
                                
                                if existing:
                                    # Update existing
                                    existing.clock_bias = r.clock_bias
                                    existing.delta_clock = r.delta_clock
                                    existing.is_outlier = r.is_outlier
                                    existing.score = r.score
                                    existing.median = r.median
                                    existing.mad = r.mad
                                else:
                                    # Insert new
                                    anomaly = SatClockAnomaly(
                                        sat_id=sat_id,
                                        epoch=r.epoch,
                                        clock_bias=r.clock_bias,
                                        delta_clock=r.delta_clock,
                                        is_outlier=r.is_outlier,
                                        score=r.score,
                                        median=r.median,
                                        mad=r.mad,
                                        detection_method='bias'
                                    )
                                    db.session.add(anomaly)
                                    total_bias += 1
                            except Exception as e:
                                logger.warning(f"Failed to save bias result for {sat_id} at {r.epoch}: {e}")
                                db.session.rollback()
                                continue
                        
                        # Save delta method results
                        for r in results_delta:
                            try:
                                existing = SatClockAnomaly.query.filter_by(
                                    sat_id=sat_id,
                                    epoch=r.epoch,
                                    detection_method='delta'
                                ).first()
                                
                                if existing:
                                    # Update existing
                                    existing.clock_bias = r.clock_bias
                                    existing.delta_clock = r.delta_clock
                                    existing.is_outlier = r.is_outlier
                                    existing.score = r.score
                                    existing.median = r.median
                                    existing.mad = r.mad
                                else:
                                    # Insert new
                                    anomaly = SatClockAnomaly(
                                        sat_id=sat_id,
                                        epoch=r.epoch,
                                        clock_bias=r.clock_bias,
                                        delta_clock=r.delta_clock,
                                        is_outlier=r.is_outlier,
                                        score=r.score,
                                        median=r.median,
                                        mad=r.mad,
                                        detection_method='delta'
                                    )
                                    db.session.add(anomaly)
                                    total_delta += 1
                            except Exception as e:
                                logger.warning(f"Failed to save delta result for {sat_id} at {r.epoch}: {e}")
                                db.session.rollback()
                                continue
                        
                        total_processed += 1
                        
                        # Commit every 5 satellites to avoid huge transactions
                        if total_processed % 5 == 0:
                            try:
                                db.session.commit()
                            except Exception as e:
                                logger.error(f"Commit failed at satellite {sat_id}: {e}")
                                db.session.rollback()
                    
                    # Final commit
                    try:
                        db.session.commit()
                    except Exception as e:
                        logger.error(f"Final commit failed: {e}")
                        db.session.rollback()
                        raise
                    
                    _recalc_running['status'] = 'completed'
                    _recalc_running['progress'] = 100
                    _recalc_running['result'] = {
                        "satellites_processed": total_processed,
                        "bias_count": total_bias,
                        "delta_count": total_delta
                    }
                    
                except Exception as e:
                    _recalc_running['status'] = 'failed'
                    _recalc_running['error'] = str(e)
                    _recalc_running['details'] = repr(e)
                    logger.error(f"Background recalculation failed: {e}", exc_info=True)
                    db.session.rollback()
        
        # Start background thread
        thread = threading.Thread(target=run_recalc_background, daemon=True)
        thread.start()
        
        return jsonify({
            "status": "started",
            "message": "Recalculation started in background"
        }), 202
    
    @app.route("/api/admin/recalculate-anomalies/status", methods=["GET"])
    def recalculate_anomalies_status():
        """Get status of background recalculation job"""
        return jsonify(_recalc_running)

    # ── Error handlers ────────────────────────────────────────────────────

    @app.errorhandler(404)
    def not_found(_):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def server_error(_):
        return jsonify({"error": "Server error"}), 500
