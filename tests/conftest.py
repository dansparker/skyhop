import pytest

from app import create_app
from app.extensions import db as _db
from app.mailer import outbox
from app.models import Aircraft, Airport, User


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "CSRF_ENABLED": False,
                      "STRIPE_SECRET_KEY": "", "STRIPE_WEBHOOK_SECRET": "", "MAIL_SERVER": "",
                      "PAYPAL_CLIENT_ID": "", "PAYPAL_CLIENT_SECRET": "", "PAYMENT_PROVIDERS": "stripe,paypal"})
    with app.app_context():
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture(autouse=True)
def clear_outbox():
    outbox.clear()
    yield outbox


@pytest.fixture
def client(app):
    return app.test_client()


def make_user(email, pilot=False, admin=False, confirmed=True):
    u = User(email=email, first_name=email.split("@")[0].title(), last_name="Test", is_admin=admin,
             email_confirmed=confirmed)
    u.set_password("password123")
    if pilot:
        u.pilot_status = "verified"
        u.license_type = "PPL"
        u.license_number = "AT.123"
        u.flight_hours = 300
    _db.session.add(u)
    _db.session.commit()
    if pilot:
        _db.session.add(Aircraft(owner_id=u.id, registration="OE-TST", manufacturer="Cessna", model="172", seats=3))
        _db.session.commit()
    return u


def login(client, email):
    return client.post("/anmelden", data={"email": email, "password": "password123"}, follow_redirects=True)


def logout(client):
    return client.post("/abmelden", follow_redirects=True)


def path_of(url):
    """'http://localhost/foo?x=1' → '/foo?x=1' (for following links from e-mails in the test client)."""
    if "://" in url:
        url = "/" + url.split("://", 1)[1].split("/", 1)[1]
    return url


@pytest.fixture
def airports(app):
    return {a.icao: a for a in Airport.query.all()}
