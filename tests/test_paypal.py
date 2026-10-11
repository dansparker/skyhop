from app import paypal
from app.extensions import db

from .conftest import login
from .test_email_payments import _accepted_booking


class FakePayPal:
    """Records calls to paypal.request and returns canned PayPal API responses."""

    def __init__(self, capture_status="COMPLETED", already_captured=False, verify="SUCCESS"):
        self.calls = []
        self.capture_status = capture_status
        self.already_captured = already_captured
        self.verify = verify

    def __call__(self, method, path, json=None, idempotency_key=None):
        self.calls.append((method, path, json))
        order = {"id": "ORDER-1", "status": "COMPLETED", "purchase_units": [
            {"payments": {"captures": [{"id": "CAP-1", "status": self.capture_status}]}}]}
        if path == "/v2/checkout/orders":
            return {"id": "ORDER-1", "status": "PAYER_ACTION_REQUIRED", "links": [
                {"rel": "self", "href": "https://api-m.sandbox.paypal.com/v2/checkout/orders/ORDER-1"},
                {"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-1"}]}
        if path.endswith("/capture"):
            if self.already_captured:
                raise paypal.PayPalError("422", 422, {"name": "UNPROCESSABLE_ENTITY",
                                                       "details": [{"issue": "ORDER_ALREADY_CAPTURED"}]})
            return order
        if method == "GET" and path.startswith("/v2/checkout/orders/"):
            return order
        if path.endswith("/refund"):
            return {"id": "REF-1", "status": "COMPLETED"}
        if path == "/v1/notifications/verify-webhook-signature":
            return {"verification_status": self.verify}
        raise AssertionError(f"unexpected call {method} {path}")


def _enable(app, monkeypatch, fake, stripe=False):
    app.config.update(PAYPAL_CLIENT_ID="cid", PAYPAL_CLIENT_SECRET="secret", PAYPAL_WEBHOOK_ID="WH-1",
                      STRIPE_SECRET_KEY="sk_test_x" if stripe else "")
    monkeypatch.setattr(paypal, "request", fake)


def test_checkout_offers_configured_providers(client, app, monkeypatch):
    b = _accepted_booking()
    login(client, "pax@x.at")
    assert 'value="demo"' in client.get(f"/buchungen/{b.id}/bezahlen").get_data(as_text=True)
    _enable(app, monkeypatch, FakePayPal(), stripe=True)
    html = client.get(f"/buchungen/{b.id}/bezahlen").get_data(as_text=True)
    assert 'value="stripe"' in html and 'value="paypal"' in html
    # Demo cannot be forced once real providers are configured
    app.config["PAYMENT_PROVIDERS"] = "paypal"
    html = client.get(f"/buchungen/{b.id}/bezahlen").get_data(as_text=True)
    assert 'value="stripe"' not in html and 'value="paypal"' in html


def test_paypal_order_capture_and_refund(client, app, monkeypatch):
    fake = FakePayPal()
    _enable(app, monkeypatch, fake, stripe=True)
    b = _accepted_booking(seats=2)
    login(client, "pax@x.at")

    r = client.post(f"/buchungen/{b.id}/bezahlen", data={"confirm": "on", "provider": "paypal"})
    assert r.status_code == 303 and "sandbox.paypal.com/checkoutnow" in r.headers["Location"]
    body = fake.calls[0][2]
    unit = body["purchase_units"][0]
    assert unit["amount"]["value"] == "200.00" and unit["amount"]["currency_code"] == "EUR"
    assert unit["items"][0]["quantity"] == "2" and unit["items"][0]["unit_amount"]["value"] == "100.00"
    assert unit["custom_id"] == str(b.id)
    ctx = body["payment_source"]["paypal"]["experience_context"]
    assert ctx["return_url"].endswith(f"/buchungen/{b.id}/paypal-zurueck")
    db.session.refresh(b)
    assert b.paypal_order_id == "ORDER-1" and b.status == "accepted"

    # Foreign/forged order token is rejected
    assert client.get(f"/buchungen/{b.id}/paypal-zurueck?token=OTHER").status_code == 403
    client.get(f"/buchungen/{b.id}/paypal-zurueck?token=ORDER-1&PayerID=X")
    db.session.refresh(b)
    assert b.status == "paid" and b.payment_provider == "paypal" and b.paypal_capture_id == "CAP-1"

    client.post(f"/buchungen/{b.id}/stornieren")
    db.session.refresh(b)
    assert b.status == "cancelled" and b.refund_status == "refunded"
    assert ("POST", "/v2/payments/captures/CAP-1/refund") in [(m, p) for m, p, _ in fake.calls]


def test_paypal_already_captured_is_idempotent(client, app, monkeypatch):
    fake = FakePayPal(already_captured=True)
    _enable(app, monkeypatch, fake)
    b = _accepted_booking()
    b.paypal_order_id = "ORDER-1"
    db.session.commit()
    login(client, "pax@x.at")
    client.get(f"/buchungen/{b.id}/paypal-zurueck?token=ORDER-1")
    db.session.refresh(b)
    assert b.status == "paid" and b.paypal_capture_id == "CAP-1"


def test_paypal_pending_capture_waits_for_webhook(client, app, monkeypatch):
    fake = FakePayPal(capture_status="PENDING")
    _enable(app, monkeypatch, fake)
    b = _accepted_booking()
    b.paypal_order_id = "ORDER-1"
    db.session.commit()
    login(client, "pax@x.at")
    r = client.get(f"/buchungen/{b.id}/paypal-zurueck?token=ORDER-1", follow_redirects=True)
    assert "wird noch verarbeitet" in r.get_data(as_text=True)
    db.session.refresh(b)
    assert b.status == "accepted"

    event = {"event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {
        "id": "CAP-1", "status": "COMPLETED", "custom_id": str(b.id),
        "supplementary_data": {"related_ids": {"order_id": "ORDER-1"}}}}
    headers = {"PAYPAL-AUTH-ALGO": "SHA256withRSA", "PAYPAL-CERT-URL": "https://api.paypal.com/cert",
               "PAYPAL-TRANSMISSION-ID": "t1", "PAYPAL-TRANSMISSION-SIG": "sig",
               "PAYPAL-TRANSMISSION-TIME": "2026-10-11T12:00:00Z"}
    app.config["CSRF_ENABLED"] = True  # webhook must work despite CSRF protection
    assert client.post("/paypal/webhook", json=event, headers=headers).status_code == 200
    db.session.refresh(b)
    assert b.status == "paid" and b.paypal_capture_id == "CAP-1"


def test_paypal_webhook_rejects_bad_signature(client, app, monkeypatch):
    _enable(app, monkeypatch, FakePayPal(verify="FAILURE"))
    b = _accepted_booking()
    b.paypal_order_id = "ORDER-1"
    db.session.commit()
    event = {"event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {
        "id": "CAP-1", "custom_id": str(b.id), "supplementary_data": {"related_ids": {"order_id": "ORDER-1"}}}}
    headers = {"PAYPAL-AUTH-ALGO": "a", "PAYPAL-CERT-URL": "c", "PAYPAL-TRANSMISSION-ID": "i",
               "PAYPAL-TRANSMISSION-SIG": "s", "PAYPAL-TRANSMISSION-TIME": "t"}
    assert client.post("/paypal/webhook", json=event, headers=headers).status_code == 400
    assert client.post("/paypal/webhook", json=event).status_code == 400  # headers missing
    db.session.refresh(b)
    assert b.status == "accepted"


def test_paypal_approved_webhook_captures_when_buyer_did_not_return(client, app, monkeypatch):
    fake = FakePayPal()
    _enable(app, monkeypatch, fake)
    b = _accepted_booking()
    b.paypal_order_id = "ORDER-1"
    db.session.commit()
    headers = {"PAYPAL-AUTH-ALGO": "a", "PAYPAL-CERT-URL": "c", "PAYPAL-TRANSMISSION-ID": "i",
               "PAYPAL-TRANSMISSION-SIG": "s", "PAYPAL-TRANSMISSION-TIME": "t"}
    client.post("/paypal/webhook", json={"event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": "ORDER-1"}},
                headers=headers)
    db.session.refresh(b)
    assert b.status == "paid"


def test_paypal_not_captured_for_cancelled_booking(client, app, monkeypatch):
    fake = FakePayPal()
    _enable(app, monkeypatch, fake)
    b = _accepted_booking()
    b.paypal_order_id = "ORDER-1"
    b.status = "cancelled"
    db.session.commit()
    from app import payments

    with app.test_request_context():
        payments.capture_paypal_order(b, "ORDER-1")
    assert not any(p.endswith("/capture") for _, p, _ in fake.calls)
