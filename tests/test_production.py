import pytest

from app import _database_url, create_app
from app.models import User

PROD = {"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "SKYHOP_ENV": "production",
        "SECRET_KEY": "x" * 48, "BASE_URL": "https://skyhop.example.at"}


def test_production_requires_strong_secret_key():
    with pytest.raises(RuntimeError, match="SKYHOP_SECRET_KEY"):
        create_app({**PROD, "SECRET_KEY": "dev-only-change-me"})
    with pytest.raises(RuntimeError):
        create_app({**PROD, "SECRET_KEY": "too-short"})


def test_production_cookies_and_security_headers():
    app = create_app(PROD)
    assert app.config["SESSION_COOKIE_SECURE"] and app.config["REMEMBER_COOKIE_SECURE"]
    r = app.test_client().get("/")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Strict-Transport-Security"].startswith("max-age=")
    assert "Referrer-Policy" in r.headers


def test_dev_mailbox_hidden_in_production():
    app = create_app(PROD)
    assert app.test_client().get("/dev/mails").status_code == 404


def test_database_url_normalisation():
    assert _database_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert _database_url("postgresql://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"
    assert _database_url("mysql://u:p@localhost/db") == "mysql+pymysql://u:p@localhost/db?charset=utf8mb4"
    assert _database_url("mysql://u:p@h/db?ssl=1") == "mysql+pymysql://u:p@h/db?ssl=1&charset=utf8mb4"
    assert _database_url("sqlite:///x.db") == "sqlite:///x.db"


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.get_json() == {"status": "ok"}


def test_create_admin_cli(app):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["create-admin", "--email", "Chef@Skyhop.at", "--first-name", "Sky",
                                 "--last-name", "Chef", "--password", "ein-sehr-langes-passwort"])
    assert result.exit_code == 0, result.output
    user = User.query.filter_by(email="chef@skyhop.at").one()
    assert user.is_admin and user.email_confirmed and user.check_password("ein-sehr-langes-passwort")
    short = runner.invoke(args=["create-admin", "--email", "b@x.at", "--first-name", "B", "--last-name", "C",
                                "--password", "kurz"])
    assert short.exit_code != 0


def test_wsgi_entry_points_import(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'wsgi.db'}")
    monkeypatch.setenv("SKYHOP_ENV", "development")
    import importlib

    import passenger_wsgi
    import wsgi

    importlib.reload(wsgi)
    importlib.reload(passenger_wsgi)
    assert passenger_wsgi.application is not None and wsgi.app is wsgi.application
