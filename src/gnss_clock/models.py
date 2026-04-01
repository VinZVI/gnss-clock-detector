from datetime import datetime, timezone

def _utcnow():
    """Naive UTC datetime для SQLite (SQLAlchemy не хранит tzinfo)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class SatClock(db.Model):
    """Сырые clock-записи, загруженные с FTP или NASA CDDIS."""
    __tablename__ = "sat_clock"

    id         = db.Column(db.Integer,  primary_key=True)
    sat_id     = db.Column(db.String(10), nullable=False, index=True)
    epoch      = db.Column(db.DateTime,   nullable=False, index=True)
    clock_bias = db.Column(db.Float,      nullable=False)   # нс
    source     = db.Column(db.String(60), default="glonass-iac")
    created_at = db.Column(db.DateTime,   default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint("sat_id", "epoch", "source", name="uix_sat_epoch_source"),
    )

    def __repr__(self):
        return f"<SatClock {self.sat_id} {self.epoch} {self.clock_bias:.2f} ns>"


class SatClockAnomaly(db.Model):
    """Результаты MAD-детекции аномалий."""
    __tablename__ = "sat_clock_anomaly"

    id              = db.Column(db.Integer,  primary_key=True)
    sat_id          = db.Column(db.String(10), nullable=False, index=True)
    epoch           = db.Column(db.DateTime,   nullable=False, index=True)
    clock_bias      = db.Column(db.Float,      nullable=False)     # нс
    delta_clock     = db.Column(db.Float)                          # нс/с
    is_outlier      = db.Column(db.Boolean,    default=False, index=True)
    score           = db.Column(db.Float)                          # |x-med|/MAD
    median          = db.Column(db.Float)
    mad             = db.Column(db.Float)
    detection_method = db.Column(db.String(10), default='bias')   # 'bias' or 'delta'
    processed_at    = db.Column(db.DateTime,   default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint("sat_id", "epoch", "detection_method", name="uix_anomaly_sat_epoch_method"),
    )

    def __repr__(self):
        flag = "⚠" if self.is_outlier else "✓"
        return f"<SatClockAnomaly {flag} {self.sat_id} {self.epoch}>"


class EtlLog(db.Model):
    """Лог запусков ETL — для дашборда и дедупликации."""
    __tablename__ = "etl_log"

    id           = db.Column(db.Integer, primary_key=True)
    started_at   = db.Column(db.DateTime, default=_utcnow, index=True)
    finished_at  = db.Column(db.DateTime)
    ftp_file     = db.Column(db.String(120))
    data_source  = db.Column(db.String(20), default="ftp")    # ftp | nasa | test
    records_raw  = db.Column(db.Integer, default=0)
    records_new  = db.Column(db.Integer, default=0)
    status       = db.Column(db.String(20), default="running")  # running|ok|error
    message      = db.Column(db.Text)
