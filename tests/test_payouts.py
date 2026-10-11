from datetime import datetime, timedelta
from types import SimpleNamespace

from app import paypal, payouts
from app.extensions import db
from app.models import Aircraft, Airport, Booking, Flight, Notification, Payout

from .conftest import login, make_user


def _past_flight(paid_seats=(1, 2), hours_ago=5, status="published"):
    """A flight in the past with paid bookings (each seat = 100 €, 10 % fee)."""
    pilot = make_user("pilot@x.at", pilot=True)
    ap = Airport.query.filter_by(icao="LOAV").one()
    f = Flight(pilot_id=pilot.id, aircraft_id=Aircraft.query.first().id, departure_id=ap.id, arrival_id=ap.id,
               flight_type="roundtrip", title="Runde", departure_time=datetime.now() - timedelta(hours=hours_ago),
               duration_minutes=60, seats_total=3, direct_cost=400, price_per_seat=100, status=status)
    db.session.add(f)
    db.session.flush()
    for i, seats in enumerate(paid_seats):
        pax = make_user(f"pax{i}@x.at")
        db.session.add(Booking(flight_id=f.id, passenger_id=pax.id, seats=seats, status="paid",
                               total_price=100 * seats, service_fee=10 * seats, paid_at=datetime.utcnow(),
                               payment_provider="demo"))
    db.session.add(Booking(flight_id=f.id, passenger_id=pilot.id, seats=1, status="cancelled",
                           total_price=100, service_fee=10))
    db.session.commit()
    return f, pilot


class FakeStripeConnect:
    def __init__(self, transfers_status="active", fail_transfer=False):
        self.calls = []
        fake = self

        class Accounts:
            def create(self, params):
                fake.calls.append(("accounts.create", params))
                return SimpleNamespace(id="acct_123")

            def retrieve(self, acct):
                return SimpleNamespace(to_dict=lambda: {"id": acct, "details_submitted": True,
                                                        "capabilities": {"transfers": transfers_status}})

            login_links = SimpleNamespace(create=lambda acct: SimpleNamespace(url="https://connect.stripe.com/express/x"))

        class AccountLinks:
            def create(self, params):
                fake.calls.append(("account_links.create", params))
                return SimpleNamespace(url="https://connect.stripe.com/setup/e/acct_123/abc")

        class Transfers:
            def create(self, params, options=None):
                import stripe

                fake.calls.append(("transfers.create", params, options))
                if fail_transfer:
                    raise stripe.InvalidRequestError("Insufficient funds", None)
                return SimpleNamespace(id="tr_123")

        self.v1 = SimpleNamespace(accounts=Accounts(), account_links=AccountLinks(), transfers=Transfers())


def test_completing_flight_schedules_payout(client, app):
    f, pilot = _past_flight()
    login(client, "pilot@x.at")
    client.post(f"/fluege/{f.id}/abschliessen")
    payout = Payout.query.one()
    # 3 seats × 100 € minus 10 % fee; cancelled booking ignored
    assert payout.amount == 270 and payout.status == "scheduled" and payout.pilot_id == pilot.id
    assert payout.due_at > datetime.utcnow() + timedelta(hours=47)
    # Not due yet → nothing happens
    payouts.execute(payout)
    assert payout.status == "scheduled"
    # Completing again doesn't create a second payout
    with app.test_request_context():
        payouts.schedule_for_flight(f)
    assert Payout.query.count() == 1


def test_demo_payout_without_providers(app):
    f, pilot = _past_flight()
    with app.test_request_context():
        payout = payouts.complete_flight(f)
        db.session.commit()
        payouts.execute(payout, force=True)
    assert payout.status == "paid" and payout.method == "demo"
    assert any("Auszahlung über 270 €" in n.text for n in Notification.query.filter_by(user_id=pilot.id))


def test_stripe_connect_onboarding_and_transfer(client, app, monkeypatch):
    app.config["STRIPE_SECRET_KEY"] = "sk_test_x"
    fake = FakeStripeConnect()
    monkeypatch.setattr(payouts, "_stripe", lambda: fake)
    f, pilot = _past_flight()
    login(client, "pilot@x.at")

    r = client.post("/pilot/auszahlungen/stripe", data={})
    assert r.status_code == 303 and r.headers["Location"].startswith("https://connect.stripe.com/setup/")
    create = fake.calls[0][1]
    assert create["type"] == "express" and create["capabilities"] == {"transfers": {"requested": True}}
    db.session.refresh(pilot)
    assert pilot.stripe_account_id == "acct_123" and not pilot.stripe_payouts_ready

    # Return from Stripe → status refreshed
    client.get("/pilot/auszahlungen?stripe=zurueck")
    db.session.refresh(pilot)
    assert pilot.stripe_payouts_ready and payouts.pilot_ready(pilot)

    client.post(f"/fluege/{f.id}/abschliessen")
    payout = Payout.query.one()
    with app.test_request_context():
        payouts.execute(payout, force=True)
    assert payout.status == "paid" and payout.method == "stripe" and payout.external_id == "tr_123"
    _, params, options = [c for c in fake.calls if c[0] == "transfers.create"][0]
    assert params["amount"] == 27000 and params["destination"] == "acct_123" and params["currency"] == "eur"
    assert options == {"idempotency_key": f"skyhop-payout-{payout.id}"}


def test_failed_transfer_is_retryable(client, app, monkeypatch):
    app.config["STRIPE_SECRET_KEY"] = "sk_test_x"
    fake = FakeStripeConnect(fail_transfer=True)
    monkeypatch.setattr(payouts, "_stripe", lambda: fake)
    f, pilot = _past_flight()
    pilot.payout_method, pilot.stripe_account_id, pilot.stripe_payouts_ready = "stripe", "acct_1", True
    db.session.commit()
    with app.test_request_context():
        payout = payouts.complete_flight(f)
        db.session.commit()
        payouts.execute(payout, force=True)
    assert payout.status == "failed" and "Insufficient funds" in payout.error and payout.attempts == 1


def test_waiting_for_details_then_paypal_payout(client, app, monkeypatch):
    app.config.update(PAYPAL_CLIENT_ID="cid", PAYPAL_CLIENT_SECRET="sec")
    calls = []

    def fake_request(method, path, json=None, idempotency_key=None):
        calls.append((method, path, json))
        if path == "/v1/payments/payouts":
            return {"batch_header": {"payout_batch_id": "BATCH-1", "batch_status": "PENDING"}}
        if path == "/v1/payments/payouts/BATCH-1":
            return {"batch_header": {"batch_status": "SUCCESS"}, "items": [{"transaction_status": "SUCCESS"}]}
        raise AssertionError(path)

    monkeypatch.setattr(paypal, "request", fake_request)
    app.config["PAYOUT_DELAY_HOURS"] = 0
    f, pilot = _past_flight()
    with app.test_request_context():
        payout = payouts.complete_flight(f)
        db.session.commit()
        payouts.execute(payout, force=True)
    assert payout.status == "waiting_details"
    assert any("fehlen noch Auszahlungsdaten" in n.text for n in Notification.query.filter_by(user_id=pilot.id))

    # Pilot enters PayPal address → waiting payout is retried immediately
    login(client, "pilot@x.at")
    client.post("/pilot/auszahlungen", data={"payout_method": "paypal", "paypal_payout_email": "Pilot@PayPal.at",
                                             "payout_country": "AT"})
    db.session.refresh(payout)
    assert payout.status == "processing" and payout.external_id == "BATCH-1"
    body = calls[0][2]
    assert body["items"][0]["receiver"] == "pilot@paypal.at"
    assert body["items"][0]["amount"] == {"currency_code": "EUR", "value": "270.00"}
    assert body["sender_batch_header"]["sender_batch_id"] == f"skyhop-payout-{payout.id}"

    with app.test_request_context():
        payouts.refresh_processing()
    db.session.refresh(payout)
    assert payout.status == "paid"


def test_cron_auto_completes_and_pays(app):
    f, pilot = _past_flight(hours_ago=30)
    app.config["PAYOUT_DELAY_HOURS"] = 0
    runner = app.test_cli_runner()
    result = runner.invoke(args=["payouts"])
    assert "1 Flüge abgeschlossen" in result.output
    db.session.refresh(f)
    assert f.status == "completed"
    assert all(b.status in ("completed", "cancelled") for b in f.bookings)
    assert Payout.query.one().status == "paid"  # demo mode


def test_recent_flight_not_auto_completed(app):
    f, _ = _past_flight(hours_ago=3)
    with app.test_request_context():
        assert payouts.auto_complete_flights() == []
    assert f.status == "published"


def test_admin_payout_actions(client, app):
    make_user("admin@x.at", admin=True)
    f, _ = _past_flight()
    with app.test_request_context():
        payout = payouts.complete_flight(f)
        db.session.commit()
    login(client, "admin@x.at")
    assert "Runde" in client.get("/admin/auszahlungen").get_data(as_text=True)
    client.post(f"/admin/auszahlungen/{payout.id}/manuell")
    db.session.refresh(payout)
    assert payout.status == "paid" and payout.method == "manual"


def test_payout_pages_render(client, app):
    f, _ = _past_flight()
    login(client, "pilot@x.at")
    client.post(f"/fluege/{f.id}/abschliessen")
    html = client.get("/pilot/auszahlungen").get_data(as_text=True)
    assert "Runde" in html and "270 €" in html
    # Non-pilots can't access
    client.post("/abmelden")
    login(client, "pax0@x.at")
    assert client.get("/pilot/auszahlungen").status_code == 302


def test_waiting_payout_back_to_scheduled_during_holding_period(client, app):
    app.config.update(PAYPAL_CLIENT_ID="cid", PAYPAL_CLIENT_SECRET="sec")
    f, pilot = _past_flight()
    with app.test_request_context():
        payout = payouts.complete_flight(f)
        payout.status = "waiting_details"
        db.session.commit()
    login(client, "pilot@x.at")
    client.post("/pilot/auszahlungen", data={"payout_method": "paypal", "paypal_payout_email": "p@pp.at"})
    db.session.refresh(payout)
    assert payout.status == "scheduled"


def test_payout_settings_render_with_both_providers(client, app):
    app.config.update(STRIPE_SECRET_KEY="sk_test_x", PAYPAL_CLIENT_ID="cid", PAYPAL_CLIENT_SECRET="sec")
    _past_flight()
    login(client, "pilot@x.at")
    html = client.get("/pilot/auszahlungen").get_data(as_text=True)
    assert 'value="stripe"' in html and 'value="paypal"' in html and "Stripe-Einrichtung starten" in html
