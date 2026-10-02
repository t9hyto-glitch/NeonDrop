"""gunicorn wsgi:app --workers 1 --threads 4 --timeout 120 (працює і gunicorn app:app — все запускається з app.py)"""
from app import app

if __name__ == "__main__":
    app.run(port=5000)
