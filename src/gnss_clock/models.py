"""Модели данных SQLAlchemy."""
from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

def _utcnow():
    """Naive UTC datetime для SQLite (SQLAlchemy не хранит tzinfo)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

db = SQLAlchemy()


class SatelliteMeta(db.Model):
    """Метаданные спутника (парсинг из .glo файлов)."""
    __tablename__ = "satellite_meta"

    sat_id = db.Column(db.String(10), primary_key=True)  # например, "R01", "G01", "R25"
    sat_type = db.Column(db.String(50))   # 'ГЛО-М', 'ГЛО-К' и т.д.
    system = db.Column(db.String(20))     # 'GLONASS', 'GPS'
    plane = db.Column(db.Integer)         # плоскость
    slot = db.Column(db.Integer)          # слот
    launch_date = db.Column(db.Date)      # дата запуска
    in_service_date = db.Column(db.Date)  # дата ввода в систему
    commission_date = db.Column(db.Date)  # дата (завершения ввода / начала летных испытаний)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    def as_dict(self):
        return {
            "sat_id": self.sat_id,
            "sat_type": self.sat_type,
            "system": self.system,
            "plane": self.plane,
            "slot": self.slot,
            "launch_date": self.launch_date.isoformat() if self.launch_date else None,
            "in_service_date": self.in_service_date.isoformat() if self.in_service_date else None,
            "commission_date": self.commission_date.isoformat() if self.commission_date else None,
        }


class SatelliteStatusHistory(db.Model):
    """Официальная история состояний (здоровье/тех.обслуживание) из .hlt файлов."""
    __tablename__ = "satellite_status_history"

    id = db.Column(db.Integer, primary_key=True)
    sat_id = db.Column(db.String(10), db.ForeignKey('satellite_meta.sat_id'), nullable=False, index=True)
    start_epoch = db.Column(db.DateTime, nullable=False, index=True)
    end_epoch = db.Column(db.DateTime, nullable=False, index=True)
    status_code = db.Column(db.Integer, nullable=False)  # 0 - Здоров, 1 - Не здоров, 3 - и т.д.
    created_at = db.Column(db.DateTime, default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint("sat_id", "start_epoch", "end_epoch", name="uix_sat_status_period"),
    )

    def as_dict(self):
        return {
            "sat_id": self.sat_id,
            "start_epoch": self.start_epoch.isoformat(),
            "end_epoch": self.end_epoch.isoformat(),
            "status_code": self.status_code,
        }


class SatClock(db.Model):
    """Сырые clock-записи, загруженные с FTP."""
    __tablename__ = "sat_clock"

    id           = db.Column(db.Integer, primary_key=True)
    sat_id       = db.Column(db.String(10), index=True) # убираем nullable=False на уровне алхимии, т.к. были ошибки в тестах без FK, или оставляем
    epoch        = db.Column(db.DateTime, nullable=False, index=True)
    clock_bias   = db.Column(db.Float, nullable=False)
    source       = db.Column(db.String(10), default="ftp")
    product_type = db.Column(db.String(10), default="ultra", index=True) # final, rapid, ultra
    created_at   = db.Column(db.DateTime, default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint("sat_id", "epoch", "product_type", name="uix_sat_epoch_product"),
    )

    def __repr__(self):
        return f"<SatClock {self.sat_id} {self.epoch} {self.product_type}>"


class SatClockAnomaly(db.Model):
    """Аномалии, найденные детектором MAD (сохранено для совместимости API)."""
    __tablename__ = "sat_clock_anomaly"
    id = db.Column(db.Integer, primary_key=True)
    sat_id = db.Column(db.String(10), index=True)
    epoch = db.Column(db.DateTime, nullable=False, index=True)
    clock_bias = db.Column(db.Float, nullable=False)
    drift = db.Column(db.Float)
    mad_score = db.Column(db.Float)
    detection_method = db.Column(db.String(10), default='bias')
    created_at = db.Column(db.DateTime, default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint("sat_id", "epoch", "detection_method", name="uix_anomaly_sat_epoch_method"),
    )


class AnalyticsCache(db.Model):
    """Кэш предварительно рассчитанных сложных метрик (вариация Аллана, суточные сводки)."""
    __tablename__ = "analytics_cache"

    id = db.Column(db.Integer, primary_key=True)
    sat_id = db.Column(db.String(10), index=True)
    date = db.Column(db.Date, nullable=False, index=True)  # за какую дату расчет
    health_index = db.Column(db.Float)                     # 0..1 (доля "здорового" времени)
    drift_rate = db.Column(db.Float)                       # линейный дрейф
    noise_rms = db.Column(db.Float)                        # RMS шума
    max_jump = db.Column(db.Float)                         # Максимальный скачок фазы
    allan_variance_json = db.Column(db.Text)               # JSON с tau и adev: {"tau": [...], "adev": [...]}
    anomaly_count = db.Column(db.Integer, default=0)       # Число MAD аномалий за сутки
    hidden_anomalies_count = db.Column(db.Integer, default=0) # Число скрытых аномалий (MAD нашел, а статус официальный==0)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        db.UniqueConstraint("sat_id", "date", name="uix_sat_date_cache"),
    )

    def as_dict(self):
        import json
        return {
            "sat_id": self.sat_id,
            "date": self.date.isoformat(),
            "health_index": self.health_index,
            "drift_rate": self.drift_rate,
            "noise_rms": self.noise_rms,
            "max_jump": self.max_jump,
            "allan_variance": json.loads(self.allan_variance_json) if self.allan_variance_json else None,
            "anomaly_count": self.anomaly_count,
            "hidden_anomalies_count": self.hidden_anomalies_count,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class EtlLog(db.Model):
    """Лог запусков ETL — для дашборда и дедупликации."""
    __tablename__ = "etl_log"

    id           = db.Column(db.Integer, primary_key=True)
    started_at   = db.Column(db.DateTime, default=_utcnow, index=True)
    finished_at  = db.Column(db.DateTime)
    ftp_file     = db.Column(db.String(120))
    processed_sats = db.Column(db.Text)  # Список спутников через запятую
    records_raw  = db.Column(db.Integer, default=0)
    records_new  = db.Column(db.Integer, default=0)
    status       = db.Column(db.String(20), default="running")
    message      = db.Column(db.Text)

    def as_dict(self):
        return {
            "id": self.id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "ftp_file": self.ftp_file,
            "processed_sats": self.processed_sats,
            "records_raw": self.records_raw,
            "records_new": self.records_new,
            "status": self.status,
            "message": self.message,
        }
