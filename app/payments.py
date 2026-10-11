"""Payments via Stripe Checkout. Without STRIPE_SECRET_KEY the app falls back to demo payments."""
import logging
from datetime import datetime

import stripe
from flask import current_app, url_for

from .extensions import db
from .mailer import absolute_url
from .models import Booking

log = logging.getLogger("skyhop.payments")


def stripe_enabled():
    return bool(current_app.config.get("STRIPE_SECRET_KEY"))


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
        "cancel_url": absolute_url(url_for("bookings.checkout", booking_id=booking.id)),
        "locale": "de",
    })
    booking.payment_provider = "stripe"
    booking.stripe_session_id = session.id
    db.session.commit()
    return session.url


def mark_paid(booking, provider, payment_intent=None):
    """Mark a booking as paid (idempotent). Returns True if the status changed."""
    from .utils import notify

    if booking.status == "paid" or booking.status == "completed":
        return False
    if booking.status != "accepted":
        # Paid although no longer payable (e.g. cancelled meanwhile) → refund immediately
        booking.payment_provider = provider
        booking.stripe_payment_intent = payment_intent
        refund(booking)
        db.session.commit()
        return False
    booking.status = "paid"
    booking.paid_at = datetime.utcnow()
    booking.payment_provider = provider
    booking.stripe_payment_intent = payment_intent
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
    """Refund a paid booking in full. Does not commit. Returns True on success."""
    if booking.payment_provider == "stripe" and booking.stripe_payment_intent:
        if not stripe_enabled():
            booking.refund_status = "manual"
            return False
        try:
            _client().v1.refunds.create(params={
                "payment_intent": booking.stripe_payment_intent,
                "metadata": {"booking_id": str(booking.id)},
            })
        except stripe.StripeError:
            log.exception("Erstattung für Buchung %s fehlgeschlagen", booking.id)
            booking.refund_status = "failed"
            return False
    booking.refund_status = "refunded"
    booking.refunded_at = datetime.utcnow()
    return True
