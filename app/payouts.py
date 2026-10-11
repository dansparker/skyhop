"""Payouts of the pilots' cost shares: Stripe Connect (Express) transfers or PayPal Payouts.

Lifecycle: a flight is completed (by the pilot, or automatically after AUTO_COMPLETE_HOURS) → a Payout is
scheduled with a holding period (PAYOUT_DELAY_HOURS) → `flask --app run payouts` (cron) or an admin executes
it. Without any provider configured, payouts are booked as "demo".
"""
import logging
from datetime import datetime, timedelta

import stripe
from flask import current_app, url_for

from . import paypal
from .extensions import db
from .mailer import absolute_url
from .models import Flight, Payout

log = logging.getLogger("skyhop.payouts")

COUNTRIES = {"AT": "Österreich", "DE": "Deutschland", "CH": "Schweiz", "IT": "Italien", "SI": "Slowenien",
             "HR": "Kroatien", "CZ": "Tschechien", "SK": "Slowakei", "HU": "Ungarn", "FR": "Frankreich",
             "NL": "Niederlande", "BE": "Belgien", "LU": "Luxemburg"}


def _stripe():
    return stripe.StripeClient(current_app.config["STRIPE_SECRET_KEY"])


def stripe_enabled():
    return bool(current_app.config.get("STRIPE_SECRET_KEY"))


def available_methods():
    methods = []
    if stripe_enabled():
        methods.append("stripe")
    if paypal.enabled():
        methods.append("paypal")
    return methods


def pilot_ready(user):
    """True if the pilot can receive money with their chosen method."""
    if user.payout_method == "stripe":
        return bool(user.stripe_account_id and user.stripe_payouts_ready)
    if user.payout_method == "paypal":
        return bool(user.paypal_payout_email)
    return False


# --- Stripe Connect onboarding -------------------------------------------------------------------

def stripe_onboarding_url(user):
    """Create (once) an Express account for the pilot and return a fresh onboarding link."""
    client = _stripe()
    if not user.stripe_account_id:
        account = client.v1.accounts.create(params={
            "type": "express",
            "country": user.payout_country or "AT",
            "email": user.email,
            "business_type": "individual",
            "capabilities": {"transfers": {"requested": True}},
            "tos_acceptance": {"service_agreement": "recipient"},
            "business_profile": {"product_description": "Kostenteilung für private Mitflüge über Skyhop"},
            "metadata": {"skyhop_user_id": str(user.id)},
        })
        user.stripe_account_id = account.id
        user.payout_method = "stripe"
        db.session.commit()
    link = client.v1.account_links.create(params={
        "account": user.stripe_account_id,
        "type": "account_onboarding",
        "refresh_url": absolute_url(url_for("pilot.stripe_onboarding")),
        "return_url": absolute_url(url_for("pilot.payouts", stripe="zurueck")),
    })
    return link.url


def refresh_stripe_status(user):
    """Read the connected account and remember whether transfers are possible."""
    if not (user.stripe_account_id and stripe_enabled()):
        return user.stripe_payouts_ready
    account = _stripe().v1.accounts.retrieve(user.stripe_account_id).to_dict()
    caps = account.get("capabilities") or {}
    ready = bool(account.get("details_submitted")) and caps.get("transfers") == "active"
    if ready != user.stripe_payouts_ready:
        user.stripe_payouts_ready = ready
        db.session.commit()
    return ready


def stripe_dashboard_url(user):
    return _stripe().v1.accounts.login_links.create(user.stripe_account_id).url


# --- Scheduling ------------------------------------------------------------------------------------

def schedule_for_flight(flight):
    """Create the payout for a completed flight (idempotent). Does not commit."""
    if flight.payout is not None:
        return flight.payout
    amount = sum(b.pilot_payout for b in flight.bookings if b.status == "completed")
    if amount <= 0:
        return None
    delay = timedelta(hours=current_app.config.get("PAYOUT_DELAY_HOURS", 48))
    payout = Payout(pilot_id=flight.pilot_id, flight_id=flight.id, amount=amount,
                    due_at=datetime.utcnow() + delay, status="scheduled")
    db.session.add(payout)
    return payout


def complete_flight(flight):
    """Mark a flight as done: bookings → completed, open requests → cancelled, payout scheduled. No commit."""
    from .utils import notify

    flight.status = "completed"
    for b in flight.bookings:
        if b.status == "paid":
            b.status = "completed"
            notify(b.passenger, f"Wie war dein Flug mit {flight.pilot.first_name}? Gib jetzt eine Bewertung ab.",
                   url_for("bookings.detail", booking_id=b.id))
        elif b.status in ("pending", "accepted"):
            b.status = "cancelled"
    db.session.flush()
    return schedule_for_flight(flight)


def auto_complete_flights():
    """Complete flights whose pilot forgot to confirm them (AUTO_COMPLETE_HOURS after landing)."""
    hours = current_app.config.get("AUTO_COMPLETE_HOURS", 24)
    cutoff = datetime.now() - timedelta(hours=hours)
    done = []
    for f in Flight.query.filter(Flight.status == "published", Flight.departure_time < cutoff).all():
        if f.arrival_time < cutoff:
            complete_flight(f)
            done.append(f)
    db.session.commit()
    return done


# --- Execution -------------------------------------------------------------------------------------

def execute(payout, force=False):
    """Try to pay out now. Commits. Returns the payout."""
    from .utils import notify

    if payout.status in ("paid", "processing"):
        return payout
    if not force and payout.due_at > datetime.utcnow():
        if payout.status == "waiting_details" and pilot_ready(payout.pilot):
            payout.status = "scheduled"  # details arrived during the holding period
            db.session.commit()
        return payout
    pilot = payout.pilot
    methods = available_methods()
    note = f"Kostenbeteiligung für „{payout.flight.title}“ am {payout.flight.departure_time:%d.%m.%Y}"

    if not methods:
        payout.method = "demo"
        _mark_paid(payout)
        return payout

    if pilot.payout_method == "stripe" and "stripe" in methods:
        refresh_stripe_status(pilot)
    if pilot.payout_method not in methods or not pilot_ready(pilot):
        if payout.status != "waiting_details":
            payout.status = "waiting_details"
            notify(pilot, f"Für deine Auszahlung über {payout.amount} € fehlen noch Auszahlungsdaten.",
                   url_for("pilot.payouts"))
        db.session.commit()
        return payout

    payout.method = pilot.payout_method
    payout.attempts += 1
    try:
        if payout.method == "stripe":
            transfer = _stripe().v1.transfers.create(
                params={
                    "amount": payout.amount * 100,
                    "currency": "eur",
                    "destination": pilot.stripe_account_id,
                    "transfer_group": f"flight-{payout.flight_id}",
                    "description": note,
                    "metadata": {"payout_id": str(payout.id), "flight_id": str(payout.flight_id)},
                },
                options={"idempotency_key": f"skyhop-payout-{payout.id}"},
            )
            payout.external_id = transfer.id
            _mark_paid(payout)
        else:
            batch_id, batch_status = paypal.create_payout(payout.id, pilot.paypal_payout_email, payout.amount, note)
            payout.external_id = batch_id
            payout.status = "processing"
            payout.error = None
            db.session.commit()
            if batch_status == "SUCCESS":
                _mark_paid(payout)
    except (stripe.StripeError, paypal.PayPalError, OSError) as e:
        log.exception("Auszahlung %s fehlgeschlagen", payout.id)
        payout.status = "failed"
        payout.error = str(getattr(e, "user_message", None) or e)[:500]
        db.session.commit()
    return payout


def refresh_processing():
    """Poll PayPal for payouts still in processing."""
    for payout in Payout.query.filter_by(status="processing", method="paypal").all():
        try:
            batch_status, item_status = paypal.get_payout_batch(payout.external_id)
        except (paypal.PayPalError, OSError):
            log.exception("Status der PayPal-Auszahlung %s nicht abrufbar", payout.id)
            continue
        if batch_status == "SUCCESS" and item_status in (None, "SUCCESS"):
            _mark_paid(payout)
        elif batch_status in ("DENIED", "CANCELED") or item_status in (
                "FAILED", "RETURNED", "BLOCKED", "REFUNDED", "REVERSED", "UNCLAIMED"):
            payout.status = "failed"
            payout.error = f"PayPal: {item_status or batch_status}"
            db.session.commit()


def run_due():
    """Cron entry point: auto-complete flights, execute due payouts, refresh pending PayPal payouts."""
    completed = auto_complete_flights()
    due = Payout.query.filter(Payout.status.in_(("scheduled", "waiting_details", "failed")),
                              Payout.due_at <= datetime.utcnow(), Payout.attempts < 5).all()
    for payout in due:
        execute(payout)
    refresh_processing()
    return {"completed_flights": len(completed), "processed": len(due)}


def _mark_paid(payout):
    from .utils import notify

    payout.status = "paid"
    payout.paid_at = datetime.utcnow()
    payout.error = None
    via = {"stripe": " auf dein Stripe-Konto", "paypal": " auf dein PayPal-Konto"}.get(payout.method, "")
    notify(payout.pilot, f"Auszahlung über {payout.amount} € für „{payout.flight.title}“ wurde{via} überwiesen.",
           url_for("pilot.payouts"))
    db.session.commit()
