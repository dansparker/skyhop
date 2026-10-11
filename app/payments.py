"""Payments: Stripe Checkout (cards, PayPal via Stripe, wallets, SEPA …) and/or direct PayPal.

Which providers are offered depends on the configured keys (optionally narrowed/ordered with
PAYMENT_PROVIDERS="stripe,paypal"). Without any keys the app falls back to demo payments.
"""
import logging
from datetime import datetime

import stripe
from flask import current_app, url_for

from . import paypal
from .extensions import db
from .mailer import absolute_url
from .models import Booking

log = logging.getLogger("skyhop.payments")


PROVIDER_LABELS = {
    "stripe": ("Karte, PayPal, Apple Pay, Google Pay, SEPA …", "Sichere Bezahlseite von Stripe"),
    "paypal": ("PayPal", "Direkt mit deinem PayPal-Konto bezahlen"),
    "demo": ("Demo-Zahlung", "Kein Zahlungsanbieter konfiguriert – es wird kein Geld bewegt"),
}


def stripe_enabled():
    return bool(current_app.config.get("STRIPE_SECRET_KEY"))


def available_providers():
    """Configured payment providers in display order; ["demo"] if none is configured."""
    configured = {"stripe": stripe_enabled(), "paypal": paypal.enabled()}
    wanted = [p.strip() for p in (current_app.config.get("PAYMENT_PROVIDERS") or "stripe,paypal").split(",")]
    providers = [p for p in wanted if configured.get(p)]
    return providers or ["demo"]


def _client():
    return stripe.StripeClient(current_app.config["STRIPE_SECRET_KEY"])


def create_checkout_session(booking):
    """Create a hosted Stripe Checkout session for an accepted booking and return its URL."""
    flight = booking.flight
    success = absolute_url(url_for("bookings.payment_success", booking_id=booking.id))
    session = _client().v1.checkout.sessions.create(params={
        "mode": "payment",
        "line_items": [{
            "quantity": booking.seats,
            "price_data": {
                "currency": "eur",
                "unit_amount": flight.price_per_seat * 100,
                "product_data": {
                    "name": f"Mitflug: {flight.title}",
                    "description": f"{flight.route_label} · {flight.departure_time:%d.%m.%Y %H:%M} Uhr",
                },
            },
        }],
        "customer_email": booking.passenger.email,
        "client_reference_id": str(booking.id),
        "metadata": {"booking_id": str(booking.id)},
        "payment_intent_data": {"metadata": {"booking_id": str(booking.id)}},
        "success_url": success + "?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": absolute_url(url_for("bookings.checkout", booking_id=booking.id, abgebrochen=1)),
        "locale": "de",
    })
    booking.payment_provider = "stripe"
    booking.stripe_session_id = session.id
    db.session.commit()
    return session.url


def _store_reference(booking, provider, reference):
    booking.payment_provider = provider
    if provider == "stripe":
        booking.stripe_payment_intent = reference
    elif provider == "paypal":
        booking.paypal_capture_id = reference


def mark_paid(booking, provider, reference=None):
    """Mark a booking as paid (idempotent). reference: Stripe PaymentIntent or PayPal capture id.

    Returns True if the status changed.
    """
    from .utils import notify

    if booking.status in ("paid", "completed"):
        return False
    if booking.status != "accepted":
        # Paid although no longer payable (e.g. cancelled meanwhile) → refund immediately
        _store_reference(booking, provider, reference)
        booking.paid_at = booking.paid_at or datetime.utcnow()
        refund(booking)
        db.session.commit()
        return False
    booking.status = "paid"
    booking.paid_at = datetime.utcnow()
    _store_reference(booking, provider, reference)
    flight = booking.flight
    link = url_for("bookings.detail", booking_id=booking.id)
    notify(flight.pilot, f"{booking.passenger.short_name} hat {booking.seats} Platz/Plätze für „{flight.title}“ bezahlt.",
           link)
    notify(booking.passenger, f"Buchung bestätigt: „{flight.title}“ am {flight.departure_time:%d.%m.%Y um %H:%M} Uhr. "
           f"Bezahlt: {booking.total_price} €.", link)
    db.session.commit()
    return True


def finalize_checkout_session(session_id):
    """Called on the success redirect: verify the session with Stripe and mark the booking paid."""
    session = _client().v1.checkout.sessions.retrieve(session_id)
    return _apply_session(session.to_dict())


def _apply_session(session):
    """session: plain dict of a Stripe Checkout Session."""
    booking_id = (session.get("metadata") or {}).get("booking_id") or session.get("client_reference_id")
    booking = db.session.get(Booking, int(booking_id)) if booking_id else None
    if booking is None:
        log.warning("Stripe-Session %s ohne gültige Buchung", session.get("id"))
        return None
    if session.get("payment_status") == "paid":
        mark_paid(booking, "stripe", session.get("payment_intent"))
    return booking


def handle_webhook(payload, sig_header):
    """Verify and process a Stripe webhook. Raises ValueError/SignatureVerificationError on bad input."""
    secret = current_app.config.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise ValueError("STRIPE_WEBHOOK_SECRET ist nicht gesetzt")
    event = stripe.Webhook.construct_event(payload, sig_header, secret).to_dict()
    if event["type"] in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        _apply_session(event["data"]["object"])
    elif event["type"] == "charge.refunded":
        pi = event["data"]["object"].get("payment_intent")
        booking = Booking.query.filter_by(stripe_payment_intent=pi).first() if pi else None
        if booking and booking.refund_status != "refunded":
            booking.refund_status = "refunded"
            booking.refunded_at = datetime.utcnow()
            db.session.commit()
    return event["type"]


def refund(booking):
    """Refund a paid booking in full via its provider. Does not commit. Returns True on success."""
    try:
        if booking.payment_provider == "stripe" and booking.stripe_payment_intent:
            if not stripe_enabled():
                booking.refund_status = "manual"
                return False
            _client().v1.refunds.create(params={
                "payment_intent": booking.stripe_payment_intent,
                "metadata": {"booking_id": str(booking.id)},
            })
        elif booking.payment_provider == "paypal" and booking.paypal_capture_id:
            if not paypal.enabled():
                booking.refund_status = "manual"
                return False
            paypal.refund_capture(booking.paypal_capture_id)
    except (stripe.StripeError, paypal.PayPalError, OSError):
        log.exception("Erstattung für Buchung %s fehlgeschlagen", booking.id)
        booking.refund_status = "failed"
        return False
    booking.refund_status = "refunded"
    booking.refunded_at = datetime.utcnow()
    return True


# --- PayPal (direct) ----------------------------------------------------------------------------

def create_paypal_order(booking):
    """Create a PayPal order for an accepted booking and return the approval URL."""
    order_id, approval_url = paypal.create_order(
        booking,
        return_url=absolute_url(url_for("bookings.paypal_return", booking_id=booking.id)),
        cancel_url=absolute_url(url_for("bookings.checkout", booking_id=booking.id, abgebrochen=1)),
    )
    booking.payment_provider = "paypal"
    booking.paypal_order_id = order_id
    db.session.commit()
    return approval_url


def capture_paypal_order(booking, order_id):
    """Capture an approved PayPal order (return redirect or webhook) and mark the booking paid."""
    if booking.status != "accepted" or order_id != booking.paypal_order_id:
        return booking  # already paid, cancelled meanwhile (approval simply expires) or foreign order
    status, capture_id = paypal.capture_order(order_id)
    if status == "COMPLETED":
        mark_paid(booking, "paypal", capture_id)
    elif capture_id:  # e.g. PENDING (eCheck/review) – completion arrives via webhook
        booking.paypal_capture_id = capture_id
        db.session.commit()
    return booking


def handle_paypal_webhook(headers, event):
    """Verify and process a PayPal webhook event (parsed JSON). Raises PayPalError on bad input."""
    if not paypal.verify_webhook(headers, event):
        raise paypal.PayPalError("Ungültige Webhook-Signatur")
    etype = event.get("event_type")
    res = event.get("resource") or {}
    if etype == "CHECKOUT.ORDER.APPROVED":
        # Buyer approved but never came back to our return URL → capture server-side
        booking = Booking.query.filter_by(paypal_order_id=res.get("id")).first()
        if booking:
            capture_paypal_order(booking, res.get("id"))
    elif etype == "PAYMENT.CAPTURE.COMPLETED":
        order_id = (res.get("supplementary_data") or {}).get("related_ids", {}).get("order_id")
        booking = Booking.query.filter_by(paypal_order_id=order_id).first() if order_id else None
        if booking and str(booking.id) == str(res.get("custom_id", booking.id)):
            mark_paid(booking, "paypal", res.get("id"))
    elif etype == "PAYMENT.CAPTURE.REFUNDED":
        booking = Booking.query.filter_by(paypal_capture_id=res.get("id")).first()
        if booking and booking.refund_status != "refunded":
            booking.refund_status = "refunded"
            booking.refunded_at = datetime.utcnow()
            db.session.commit()
    return etype
