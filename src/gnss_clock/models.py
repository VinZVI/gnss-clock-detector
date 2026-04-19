"""Модели данных SQLAlchemy."""
from datetime import datetime, timezone

def _utcnow():
    """Naive UTC datetime для SQLite (SQLAlchemy не хранит tzinfo)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class SatClock(db.Model):
    """Сырые clock-записи, загруженные с FTP."""
    __tablename__ = "sat_clock"

    id           = db.Column(db.Integer, primary_key=True)
    sat_id       = db.Column(db.String(10), nullable=False, index=True)
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


class EtlLog(db.Model):
    """Лог запусков ETL — для дашборда и дедупликации."""
    __tablename__ = "etl_log"

    id           = db.Column(db.Integer, primary_key=True)
    started_at   = db.Column(db.DateTime, default=_utcnow, index=True)
    finished_at  = db.Column(db.DateTime)
    ftp_file     = db.Column(db.String(120))
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
            "records_raw": self.records_raw,
            "records_new": self.records_new,
            "status": self.status,
            "message": self.message,
        }
