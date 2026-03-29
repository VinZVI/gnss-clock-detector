# Build Commands
pip install -e .

# Start Command
gunicorn wsgi:app --bind 0.0.0.0:$PORT
