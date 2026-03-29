"""
WSGI entry point для PythonAnywhere.

В настройках Web app:
    Source code:  /home/<user>/gnss-clock-detector
    WSGI file:    /home/<user>/gnss-clock-detector/wsgi.py
    Virtualenv:   /home/<user>/gnss-clock-detector/.venv
"""

import sys
import os

# Добавляем src/ в путь (нужно если пакет не установлен через pip install -e .)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from gnss_clock.app import create_app

# Create Flask application
app = create_app()

# WSGI compatible name
application = app

if __name__ == "__main__":
    from gnss_clock import config
    application.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
    )
