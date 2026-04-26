import re

with open("src/gnss_clock/etl.py", "r", encoding="utf-8") as f:
    content = f.read()

new_get_app = """def _get_app():
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
    return app"""

content = re.sub(r'def _get_app\(\):.*?(?=\n\n\ndef )', new_get_app, content, flags=re.DOTALL)

with open("src/gnss_clock/etl.py", "w", encoding="utf-8") as f:
    f.write(content)
