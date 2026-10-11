"""Direct PayPal integration (REST API v2: Orders, Captures, Refunds, Webhook verification)."""
import logging
import time
import uuid

import requests
from flask import current_app

log = logging.getLogger("skyhop.paypal")

API_BASE = {"sandbox": "https://api-m.sandbox.paypal.com", "live": "https://api-m.paypal.com"}
_token_cache = {}


class PayPalError(Exception):
    def __init__(self, message, status=None, details=None):
        super().__init__(message)
        self.status = status
        self.details = details or {}

    @property
    def issue(self):
        """First issue code of a PayPal error response, e.g. ORDER_ALREADY_CAPTURED."""
        for d in self.details.get("details", []):
            if d.get("issue"):
                return d["issue"]
        return self.details.get("name")


def enabled():
    cfg = current_app.config
    return bool(cfg.get("PAYPAL_CLIENT_ID") and cfg.get("PAYPAL_CLIENT_SECRET"))


def _base():
    return API_BASE.get(current_app.config.get("PAYPAL_MODE", "sandbox"), API_BASE["sandbox"])


def _access_token():
    cfg = current_app.config
    key = (_base(), cfg["PAYPAL_CLIENT_ID"])
    cached = _token_cache.get(key)
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    r = requests.post(f"{_base()}/v1/oauth2/token", data={"grant_type": "client_credentials"},
                      auth=(cfg["PAYPAL_CLIENT_ID"], cfg["PAYPAL_CLIENT_SECRET"]), timeout=20)
    if r.status_code != 200:
        raise PayPalError("PayPal-Authentifizierung fehlgeschlagen", r.status_code, _json(r))
    data = r.json()
    _token_cache[key] = (data["access_token"], time.time() + int(data.get("expires_in", 300)))
    return data["access_token"]


def _json(r):
    try:
        return r.json()
    except ValueError:
        return {}


def request(method, path, json=None, idempotency_key=None):
    """Authenticated call to the PayPal REST API. Returns the decoded JSON body."""
    headers = {"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json",
               "Prefer": "return=representation"}
    if idempotency_key:
        headers["PayPal-Request-Id"] = idempotency_key
    r = requests.request(method, _base() + path, json=json, headers=headers, timeout=30)
    if r.status_code >= 400:
        raise PayPalError(f"PayPal-Fehler {r.status_code} bei {path}", r.status_code, _json(r))
    return _json(r)


def _money(euros):
    return {"currency_code": "EUR", "value": f"{euros:.2f}"}


def create_order(booking, return_url, cancel_url):
    """Create an order and return (order_id, approval_url)."""
    flight = booking.flight
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": f"booking-{booking.id}",
            "custom_id": str(booking.id),
            "description": f"Mitflug: {flight.title}"[:127],
            "amount": {**_money(booking.total_price),
                       "breakdown": {"item_total": _money(booking.total_price)}},
            "items": [{
                "name": f"Mitflug: {flight.title}"[:127],
                "description": f"{flight.route_label} · {flight.departure_time:%d.%m.%Y %H:%M} Uhr"[:127],
                "quantity": str(booking.seats),
                "unit_amount": _money(flight.price_per_seat),
                "category": "DIGITAL_GOODS",
            }],
        }],
        "payment_source": {"paypal": {"experience_context": {
            "brand_name": "Skyhop",
            "locale": "de-AT",
            "shipping_preference": "NO_SHIPPING",
            "user_action": "PAY_NOW",
            "return_url": return_url,
            "cancel_url": cancel_url,
        }}},
    }
    order = request("POST", "/v2/checkout/orders", body, idempotency_key=str(uuid.uuid4()))
    approval = next((l["href"] for l in order.get("links", []) if l.get("rel") in ("payer-action", "approve")), None)
    if not approval:
        raise PayPalError("PayPal hat keinen Freigabe-Link geliefert", details=order)
    return order["id"], approval


def capture_order(order_id):
    """Capture an approved order. Returns (status, capture_id). Safe to call twice."""
    try:
        order = request("POST", f"/v2/checkout/orders/{order_id}/capture", {},
                        idempotency_key=f"capture-{order_id}")
    except PayPalError as e:
        if e.issue != "ORDER_ALREADY_CAPTURED":
            raise
        order = request("GET", f"/v2/checkout/orders/{order_id}")
    return _capture_from_order(order)


def _capture_from_order(order):
    for unit in order.get("purchase_units", []):
        for cap in unit.get("payments", {}).get("captures", []):
            return cap.get("status"), cap.get("id")
    return order.get("status"), None


def refund_capture(capture_id):
    return request("POST", f"/v2/payments/captures/{capture_id}/refund",
                   {"note_to_payer": "Erstattung deiner Skyhop-Buchung"},
                   idempotency_key=f"refund-{capture_id}")


def verify_webhook(headers, event):
    """Let PayPal verify the webhook signature. Returns True if genuine."""
    webhook_id = current_app.config.get("PAYPAL_WEBHOOK_ID")
    if not webhook_id:
        raise PayPalError("PAYPAL_WEBHOOK_ID ist nicht gesetzt")
    body = {
        "auth_algo": headers.get("PAYPAL-AUTH-ALGO"),
        "cert_url": headers.get("PAYPAL-CERT-URL"),
        "transmission_id": headers.get("PAYPAL-TRANSMISSION-ID"),
        "transmission_sig": headers.get("PAYPAL-TRANSMISSION-SIG"),
        "transmission_time": headers.get("PAYPAL-TRANSMISSION-TIME"),
        "webhook_id": webhook_id,
        "webhook_event": event,
    }
    if not all(body.values()):
        return False
    result = request("POST", "/v1/notifications/verify-webhook-signature", body)
    return result.get("verification_status") == "SUCCESS"
