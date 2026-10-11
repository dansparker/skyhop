"""Production entry point (Gunicorn, Passenger, `flask --app wsgi ...`).

Loads settings from the .env file next to this file, then creates the app.
"""
import os

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:  # python-dotenv is optional if the environment is set elsewhere
    pass

from app import create_app  # noqa: E402

app = application = create_app()
