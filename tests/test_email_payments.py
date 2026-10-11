import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

from app import payments
from app.extensions import db
from app.mailer import make_token, outbox
from app.models import Aircraft, Airport, Booking, Flight, NewsletterSubscriber, User

from .conftest import login, logout, make_user, path_of


def _register(client, email="eva@example.com", **extra):
    data = {"first_name": "Eva", "last_name": "Muster", "email": email,
            "password": "geheim123", "password2": "geheim123", "terms": "on"}
    data.update(extra)
    return client.post("/registrieren", data=data, follow_redirects=True)


# --- Double opt-in for accounts -------------------------------------------------------------

def test_registration_sends_confirmation_and_blocks_actions(client):
    _register(client)
    user = User.query.filter_by(email="eva@example.com").one()
    assert not user.email_confirmed
    assert len(outbox) == 1 and outbox[0]["to"] == "eva@example.com"
    assert "/email-bestaetigen/" in outbox[0]["action_url"]

    # Unconfirmed users can browse but not book / write / post wishes
    assert client.get("/flugwuensche/neu").headers["Location"].endswith("/email-bestaetigen")
    assert "Bitte bestätige deine E-Mail-Adresse" in client.get("/").get_data(as_text=True)

    client.get(path_of(outbox[0]["action_url"]))
    db.session.refresh(user)
    assert user.email_confirmed and user.email_confirmed_at
    assert client.get("/flugwuensche/neu").status_code == 200


def test_confirmation_link_tampered_or_wrong_email(client):
    _register(client)
    link = path_of(outbox[0]["action_url"])
    assert "ungültig" in client.get(link + "x", follow_redirects=True).get_data(as_text=True)
    # Token is bound to the address: changing the e-mail invalidates it
    user = User.query.one()
    user.email = "other@example.com"
    db.session.commit()
    client.get(link)
    db.session.refresh(user)
    assert not user.email_confirmed


def test_resend_confirmation_is_rate_limited(client):
    _register(client)
    r = client.post("/email-bestaetigen", follow_redirects=True)
    assert "warte eine Minute" in r.get_data(as_text=True)
    assert len(outbox) == 1


def test_notifications_are_emailed_to_confirmed_users_only(client):
    pilot = make_user("anna@x.at", pilot=True)
    make_user("p@x.at")
    login(client, "anna@x.at")
    when = datetime.now() + timedelta(days=3)
    client.post("/fluege/neu", data={"flight_type": "roundtrip", "title": "Runde", "departure": "LOAV",
                                     "date": when.strftime("%Y-%m-%d"), "time": "10:00", "duration_minutes": "60",
                                     "aircraft_id": "1", "seats_total": "3", "direct_cost": "400"})
    logout(client)
    flight = Flight.query.one()
    login(client, "p@x.at")
    outbox.clear()
    client.post(f"/fluege/{flight.id}/buchen", data={"seats": "1"})
    assert [m["to"] for m in outbox] == ["anna@x.at"]
    # Pilot opted out of e-mail notifications → in-app only
    pilot.email_notifications = False
    db.session.commit()
    outbox.clear()
    client.post(f"/buchungen/{Booking.query.one().id}/stornieren")
    assert len(outbox) == 0


# --- Password reset -------------------------------------------------------------------------

def test_password_reset_flow(client):
    make_user("r@x.at")
    r = client.post("/passwort-vergessen", data={"email": "unknown@x.at"}, follow_redirects=True)
    assert "Falls ein Konto" in r.get_data(as_text=True)
    assert len(outbox) == 0  # no mail, but the same answer (no account enumeration)
    client.post("/passwort-vergessen", data={"email": "r@x.at"})
    link = path_of(outbox[0]["action_url"])
    client.post(link, data={"new": "neuespasswort", "new2": "neuespasswort"})
    user = User.query.filter_by(email="r@x.at").one()
    assert user.check_password("neuespasswort")
    # Single use: the token is invalid once the password changed
    r = client.post(link, data={"new": "nochmal12345", "new2": "nochmal12345"}, follow_redirects=True)
    assert "ungültig" in r.get_data(as_text=True)
    assert user.check_password("neuespasswort")


# --- Newsletter double opt-in ---------------------------------------------------------------

def test_newsletter_double_opt_in(client):
    client.post("/newsletter/", data={"email": "nl@example.com"})  # consent checkbox missing
    assert NewsletterSubscriber.query.count() == 0
    client.post("/newsletter/", data={"email": "NL@example.com", "consent": "on"})
    sub = NewsletterSubscriber.query.one()
    assert sub.email == "nl@example.com" and sub.status == "pending" and sub.request_ip
    link = path_of(outbox[0]["action_url"])
    # GET only shows a confirm button – mail-filter link scanners must not opt people in
    assert client.get(link).status_code == 200
    db.session.refresh(sub)
    assert sub.status == "pending"
    client.post(link)
    db.session.refresh(sub)
    assert sub.status == "confirmed" and sub.confirmed_at and sub.confirm_ip
    assert "Newsletter abbestellen" in outbox[0]["html"]
    client.post(f"/newsletter/abmelden/{make_token('newsletter-unsub', sub.id)}")
    db.session.refresh(sub)
    assert sub.status == "unsubscribed" and sub.unsubscribed_at


def test_newsletter_signup_at_registration(client):
    _register(client, newsletter="on")
    assert {m["subject"] for m in outbox} == {"Bitte bestätige deine E-Mail-Adresse",
                                              "Bitte bestätige deine Newsletter-Anmeldung"}
    assert NewsletterSubscriber.query.one().status == "pending"


def test_newsletter_admin_export(client):
    make_user("admin@x.at", admin=True)
    db.session.add(NewsletterSubscriber(email="a@b.at", status="confirmed", confirmed_at=datetime.utcnow(),
                                        confirm_ip="1.2.3.4"))
    db.session.add(NewsletterSubscriber(email="pending@b.at", status="pending"))
    db.session.commit()
    login(client, "admin@x.at")
    csv = client.get("/admin/newsletter.csv").get_data(as_text=True)
    assert "a@b.at" in csv and "1.2.3.4" in csv and "pending@b.at" not in csv


# --- Payments (Stripe) ----------------------------------------------------------------------

def _accepted_booking(seats=1):
    pilot = make_user("pilot@x.at", pilot=True)
    passenger = make_user("pax@x.at")
    ap = Airport.query.filter_by(icao="LOAV").one()
    f = Flight(pilot_id=pilot.id, aircraft_id=Aircraft.query.first().id, departure_id=ap.id, arrival_id=ap.id,
               flight_type="roundtrip", title="Runde", departure_time=datetime.now() + timedelta(days=2),
               duration_minutes=60, seats_total=3, direct_cost=400, price_per_seat=100)
    db.session.add(f)
    db.session.flush()
    b = Booking(flight_id=f.id, passenger_id=passenger.id, seats=seats, status="accepted",
                total_price=100 * seats, service_fee=10 * seats)
    db.session.add(b)
    db.session.commit()
    return b


class FakeStripe:
    """Stand-in for stripe.StripeClient (only the calls Skyhop uses)."""

    def __init__(self):
        self.created, self.refunds, self.booking_id = [], [], None
        fake = self

        class Sessions:
            def create(self, params):
                fake.created.append(params)
                return SimpleNamespace(id="cs_test_123", url="https://checkout.stripe.com/c/pay/cs_test_123")

            def retrieve(self, sid):
                return SimpleNamespace(to_dict=lambda: {
                    "id": sid, "payment_status": "paid", "payment_intent": "pi_123",
                    "metadata": {"booking_id": str(fake.booking_id)}})

        class Refunds:
            def create(self, params):
                fake.refunds.append(params)

        self.v1 = SimpleNamespace(checkout=SimpleNamespace(sessions=Sessions()), refunds=Refunds())


def test_demo_payment_without_stripe(client):
    b = _accepted_booking()
    login(client, "pax@x.at")
    client.post(f"/buchungen/{b.id}/bezahlen", data={"confirm": "on"})
    db.session.refresh(b)
    assert b.status == "paid" and b.payment_provider == "demo"


def test_stripe_checkout_success_and_refund(client, app, monkeypatch):
    app.config["STRIPE_SECRET_KEY"] = "sk_test_dummy"
    fake = FakeStripe()
    monkeypatch.setattr(payments, "_client", lambda: fake)
    b = _accepted_booking(seats=2)
    fake.booking_id = b.id
    login(client, "pax@x.at")

    r = client.post(f"/buchungen/{b.id}/bezahlen", data={"confirm": "on"})
    assert r.status_code == 303 and r.headers["Location"].startswith("https://checkout.stripe.com/")
    params = fake.created[0]
    assert params["line_items"][0]["price_data"]["unit_amount"] == 10000
    assert params["line_items"][0]["quantity"] == 2
    assert params["success_url"].endswith("?session_id={CHECKOUT_SESSION_ID}")
    db.session.refresh(b)
    assert b.status == "accepted" and b.stripe_session_id == "cs_test_123"

    # A forged session id is rejected
    assert client.get(f"/buchungen/{b.id}/zahlung-erfolgreich?session_id=cs_evil").status_code == 403
    client.get(f"/buchungen/{b.id}/zahlung-erfolgreich?session_id=cs_test_123")
    db.session.refresh(b)
    assert b.status == "paid" and b.stripe_payment_intent == "pi_123"
    assert {m["to"] for m in outbox} >= {"pax@x.at", "pilot@x.at"}  # confirmation mails

    # Cancelling refunds via Stripe
    client.post(f"/buchungen/{b.id}/stornieren")
    db.session.refresh(b)
    assert b.status == "cancelled" and b.refund_status == "refunded"
    assert fake.refunds == [{"payment_intent": "pi_123", "metadata": {"booking_id": str(b.id)}}]


def _signed(payload, secret):
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def test_stripe_webhook_marks_paid_and_verifies_signature(client, app):
    app.config.update(STRIPE_SECRET_KEY="sk_test_dummy", STRIPE_WEBHOOK_SECRET="whsec_test", CSRF_ENABLED=True)
    b = _accepted_booking()
    payload = json.dumps({
        "id": "evt_1", "object": "event", "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_1", "object": "checkout.session", "payment_status": "paid",
                            "payment_intent": "pi_wh", "metadata": {"booking_id": str(b.id)}}},
    })
    bad = client.post("/stripe/webhook", data=payload, headers={"Stripe-Signature": "t=1,v1=deadbeef"},
                      content_type="application/json")
    assert bad.status_code == 400
    ok = client.post("/stripe/webhook", data=payload, headers={"Stripe-Signature": _signed(payload, "whsec_test")},
                     content_type="application/json")
    assert ok.status_code == 200
    db.session.refresh(b)
    assert b.status == "paid" and b.stripe_payment_intent == "pi_wh"
    # Idempotent: the same event again changes nothing
    paid_at = b.paid_at
    client.post("/stripe/webhook", data=payload, headers={"Stripe-Signature": _signed(payload, "whsec_test")},
                content_type="application/json")
    db.session.refresh(b)
    assert b.paid_at == paid_at


def test_pilot_cancel_refunds_stripe_payments(client, app, monkeypatch):
    app.config["STRIPE_SECRET_KEY"] = "sk_test_dummy"
    fake = FakeStripe()
    monkeypatch.setattr(payments, "_client", lambda: fake)
    b = _accepted_booking()
    with app.test_request_context():
        payments.mark_paid(b, "stripe", "pi_x")
    login(client, "pilot@x.at")
    client.post(f"/fluege/{b.flight_id}/absagen", data={"reason": "Wetter"})
    db.session.refresh(b)
    assert b.status == "cancelled" and b.refund_status == "refunded"
    assert fake.refunds[0]["payment_intent"] == "pi_x"


def test_payment_for_cancelled_booking_is_refunded(client, app, monkeypatch):
    app.config["STRIPE_SECRET_KEY"] = "sk_test_dummy"
    fake = FakeStripe()
    monkeypatch.setattr(payments, "_client", lambda: fake)
    b = _accepted_booking()
    b.status = "cancelled"
    db.session.commit()
    with app.test_request_context():
        payments.mark_paid(b, "stripe", "pi_late")
    assert b.status == "cancelled" and b.refund_status == "refunded"
    assert fake.refunds[0]["payment_intent"] == "pi_late"
