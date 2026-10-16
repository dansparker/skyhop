from datetime import datetime

import stripe
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import payments, paypal
from ..extensions import db
from ..models import Booking, Flight, Review
from ..utils import confirmed_required, get_or_create_conversation, notify, parse_int

bp = Blueprint("bookings", __name__)


@bp.route("/dashboard")
@login_required
def dashboard():
    tab = request.args.get("tab", "passenger")
    my_bookings = (
        Booking.query.filter_by(passenger_id=current_user.id).order_by(Booking.created_at.desc()).all()
    )
    upcoming_bookings = [b for b in my_bookings if not b.flight.is_past and b.status in ("pending", "accepted", "paid")]
    past_bookings = [b for b in my_bookings if b not in upcoming_bookings]
    my_flights = Flight.query.filter_by(pilot_id=current_user.id).order_by(Flight.departure_time.desc()).all()
    upcoming_flights = [f for f in my_flights if f.status == "published" and not f.is_past]
    upcoming_flights.sort(key=lambda f: f.departure_time)
    past_flights = [f for f in my_flights if f not in upcoming_flights]
    open_requests = sum(len(f.pending_requests) for f in upcoming_flights)
    earnings = sum(
        b.pilot_payout for f in my_flights for b in f.bookings if b.status in ("paid", "completed")
    )
    return render_template(
        "bookings/dashboard.html",
        tab=tab,
        upcoming_bookings=upcoming_bookings,
        past_bookings=past_bookings,
        upcoming_flights=upcoming_flights,
        past_flights=past_flights,
        open_requests=open_requests,
        earnings=earnings,
    )


@bp.route("/fluege/<int:flight_id>/buchen", methods=["POST"])
@confirmed_required
def request_booking(flight_id):
    flight = db.session.get(Flight, flight_id) or abort(404)
    if flight.pilot_id == current_user.id:
        flash("Du kannst deinen eigenen Flug nicht buchen.", "warning")
        return redirect(url_for("flights.detail", flight_id=flight.id))
    if not flight.is_bookable:
        flash("Dieser Flug ist nicht mehr buchbar.", "warning")
        return redirect(url_for("flights.detail", flight_id=flight.id))
    existing = Booking.query.filter_by(flight_id=flight.id, passenger_id=current_user.id).filter(
        Booking.status.in_(("pending", "accepted", "paid"))
    ).first()
    if existing:
        flash("Du hast für diesen Flug bereits eine Anfrage gestellt.", "info")
        return redirect(url_for("bookings.detail", booking_id=existing.id))
    seats = parse_int(request.form.get("seats"), None, 1, flight.seats_available)
    if not seats:
        flash(f"Bitte wähle zwischen 1 und {flight.seats_available} Plätzen.", "danger")
        return redirect(url_for("flights.detail", flight_id=flight.id))
    message = request.form.get("message", "").strip()
    total = seats * flight.price_per_seat
    fee = round(total * current_app.config["SERVICE_FEE_RATE"])
    booking = Booking(flight_id=flight.id, passenger_id=current_user.id, seats=seats, message=message,
                      total_price=total, service_fee=fee)
    db.session.add(booking)
    db.session.flush()
    if message:
        conv = get_or_create_conversation(current_user, flight.pilot, flight)
        from ..models import Message

        db.session.add(Message(conversation_id=conv.id, sender_id=current_user.id, body=message))
        conv.updated_at = datetime.utcnow()
    notify(flight.pilot, f"{current_user.short_name} möchte {seats} {'Platz' if seats == 1 else 'Plätze'} für „{flight.title}“ buchen.",
           url_for("bookings.detail", booking_id=booking.id))
    db.session.commit()
    flash("Deine Anfrage wurde an den Piloten gesendet. Du wirst benachrichtigt, sobald sie beantwortet ist.",
          "success")
    return redirect(url_for("bookings.detail", booking_id=booking.id))


def _get_booking_for_member(booking_id):
    booking = db.session.get(Booking, booking_id) or abort(404)
    if current_user.id not in (booking.passenger_id, booking.flight.pilot_id) and not current_user.is_admin:
        abort(403)
    return booking


@bp.route("/buchungen/<int:booking_id>")
@login_required
def detail(booking_id):
    booking = _get_booking_for_member(booking_id)
    is_pilot = booking.flight.pilot_id == current_user.id
    my_review = booking.review_by(current_user)
    return render_template("bookings/detail.html", booking=booking, flight=booking.flight,
                           is_pilot=is_pilot, my_review=my_review)


@bp.route("/buchungen/<int:booking_id>/annehmen", methods=["POST"])
@login_required
def accept(booking_id):
    booking = _get_booking_for_member(booking_id)
    flight = booking.flight
    if flight.pilot_id != current_user.id or booking.status != "pending":
        abort(403)
    if booking.seats > flight.seats_available:
        flash("Nicht mehr genügend freie Plätze für diese Anfrage.", "danger")
        return redirect(url_for("bookings.detail", booking_id=booking.id))
    booking.status = "accepted"
    notify(booking.passenger, f"{current_user.first_name} hat deine Anfrage für „{flight.title}“ angenommen! "
           "Schließe jetzt die Zahlung ab.", url_for("bookings.checkout", booking_id=booking.id))
    db.session.commit()
    flash("Anfrage angenommen. Der Passagier wurde benachrichtigt.", "success")
    return redirect(request.form.get("next") or url_for("bookings.detail", booking_id=booking.id))


@bp.route("/buchungen/<int:booking_id>/ablehnen", methods=["POST"])
@login_required
def decline(booking_id):
    booking = _get_booking_for_member(booking_id)
    if booking.flight.pilot_id != current_user.id or booking.status not in ("pending", "accepted"):
        abort(403)
    booking.status = "declined"
    notify(booking.passenger, f"Deine Anfrage für „{booking.flight.title}“ wurde leider abgelehnt.",
           url_for("flights.search", **{"from": booking.flight.departure.city}))
    db.session.commit()
    flash("Anfrage abgelehnt.", "info")
    return redirect(request.form.get("next") or url_for("bookings.detail", booking_id=booking.id))


@bp.route("/buchungen/<int:booking_id>/bezahlen", methods=["GET", "POST"])
@login_required
def checkout(booking_id):
    booking = _get_booking_for_member(booking_id)
    if booking.passenger_id != current_user.id:
        abort(403)
    if booking.status != "accepted":
        flash("Diese Buchung kann gerade nicht bezahlt werden.", "info")
        return redirect(url_for("bookings.detail", booking_id=booking.id))
    if request.method == "POST":
        if not request.form.get("confirm"):
            flash("Bitte bestätige die Buchungsbedingungen.", "danger")
            return redirect(url_for("bookings.checkout", booking_id=booking.id))
        if booking.flight.is_past:
            flash("Dieser Flug hat bereits stattgefunden.", "warning")
            return redirect(url_for("bookings.detail", booking_id=booking.id))
        providers = payments.available_providers()
        provider = request.form.get("provider") if request.form.get("provider") in providers else providers[0]
        try:
            if provider == "stripe":
                return redirect(payments.create_checkout_session(booking), code=303)
            if provider == "paypal":
                return redirect(payments.create_paypal_order(booking), code=303)
        except (stripe.StripeError, paypal.PayPalError, OSError):
            current_app.logger.exception("Checkout (%s) für Buchung %s fehlgeschlagen", provider, booking.id)
            flash("Der Zahlungsdienst ist gerade nicht erreichbar. Bitte versuche es später erneut.", "danger")
            return redirect(url_for("bookings.checkout", booking_id=booking.id))
        if provider != "demo":
            abort(400)
        payments.mark_paid(booking, "demo")
        flash("Zahlung erfolgreich – du fliegst mit! ✈️", "success")
        return redirect(url_for("bookings.detail", booking_id=booking.id))
    if request.args.get("abgebrochen"):
        flash("Die Zahlung wurde abgebrochen. Du kannst es jederzeit erneut versuchen.", "info")
    providers = payments.available_providers()
    return render_template("bookings/checkout.html", booking=booking, flight=booking.flight,
                           providers=providers, labels=payments.PROVIDER_LABELS)


@bp.route("/buchungen/<int:booking_id>/paypal-zurueck")
@login_required
def paypal_return(booking_id):
    booking = _get_booking_for_member(booking_id)
    order_id = request.args.get("token", "")
    if booking.passenger_id != current_user.id or not order_id or order_id != booking.paypal_order_id:
        abort(403)
    try:
        payments.capture_paypal_order(booking, order_id)
    except (paypal.PayPalError, OSError) as e:
        current_app.logger.exception("PayPal-Capture für Buchung %s fehlgeschlagen", booking.id)
        if isinstance(e, paypal.PayPalError) and e.issue == "INSTRUMENT_DECLINED":
            flash("PayPal hat die Zahlungsquelle abgelehnt. Bitte wähle eine andere und versuche es erneut.", "danger")
            return redirect(url_for("bookings.checkout", booking_id=booking.id))
    db.session.refresh(booking)
    if booking.status == "paid":
        flash("Zahlung erfolgreich – du fliegst mit! ✈️", "success")
    else:
        flash("Deine Zahlung wird noch verarbeitet. Du bekommst eine Bestätigung, sobald sie eingegangen ist.", "info")
    return redirect(url_for("bookings.detail", booking_id=booking.id))


@bp.route("/paypal/webhook", methods=["POST"])
def paypal_webhook():
    event = request.get_json(silent=True)
    if not isinstance(event, dict):
        return {"error": "invalid"}, 400
    try:
        event_type = payments.handle_paypal_webhook(request.headers, event)
    except (paypal.PayPalError, OSError) as e:
        current_app.logger.warning("Ungültiger PayPal-Webhook: %s", e)
        return {"error": "invalid"}, 400
    return {"received": event_type}, 200


@bp.route("/buchungen/<int:booking_id>/zahlung-erfolgreich")
@login_required
def payment_success(booking_id):
    booking = _get_booking_for_member(booking_id)
    session_id = request.args.get("session_id", "")
    if booking.passenger_id != current_user.id or not session_id or session_id != booking.stripe_session_id:
        abort(403)
    try:
        payments.finalize_checkout_session(session_id)
    except stripe.StripeError:
        current_app.logger.exception("Stripe-Session %s konnte nicht geprüft werden", session_id)
    db.session.refresh(booking)
    if booking.status == "paid":
        flash("Zahlung erfolgreich – du fliegst mit! ✈️", "success")
    else:
        flash("Deine Zahlung wird noch verarbeitet. Du bekommst eine Bestätigung, sobald sie eingegangen ist.", "info")
    return redirect(url_for("bookings.detail", booking_id=booking.id))


@bp.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    try:
        event_type = payments.handle_webhook(request.get_data(), request.headers.get("Stripe-Signature"))
    except (ValueError, stripe.SignatureVerificationError) as e:
        current_app.logger.warning("Ungültiger Stripe-Webhook: %s", e)
        return {"error": "invalid"}, 400
    return {"received": event_type}, 200


@bp.route("/buchungen/<int:booking_id>/stornieren", methods=["POST"])
@login_required
def cancel(booking_id):
    booking = _get_booking_for_member(booking_id)
    if booking.passenger_id != current_user.id or booking.status not in ("pending", "accepted", "paid"):
        abort(403)
    if booking.flight.is_past:
        flash("Vergangene Flüge können nicht storniert werden.", "warning")
        return redirect(url_for("bookings.detail", booking_id=booking.id))
    was_paid = booking.status == "paid"
    booking.status = "cancelled"
    if was_paid:
        payments.refund(booking)
    notify(booking.flight.pilot, f"{current_user.short_name} hat die Buchung für „{booking.flight.title}“ storniert.",
           url_for("flights.detail", flight_id=booking.flight_id))
    db.session.commit()
    msg = "Buchung storniert."
    if was_paid and booking.refund_status == "refunded":
        msg += f" {booking.total_price} € werden auf dein Zahlungsmittel zurückerstattet."
    elif was_paid:
        msg += " Die Erstattung wird von unserem Team manuell bearbeitet."
    flash(msg, "info")
    return redirect(url_for("bookings.dashboard"))


@bp.route("/buchungen/<int:booking_id>/bewerten", methods=["POST"])
@login_required
def review(booking_id):
    booking = _get_booking_for_member(booking_id)
    if not booking.is_reviewable:
        flash("Bewertungen sind erst nach dem Flug möglich.", "warning")
        return redirect(url_for("bookings.detail", booking_id=booking.id))
    if booking.review_by(current_user):
        flash("Du hast bereits eine Bewertung abgegeben.", "info")
        return redirect(url_for("bookings.detail", booking_id=booking.id))
    rating = parse_int(request.form.get("rating"), None, 1, 5)
    if not rating:
        flash("Bitte vergib 1 bis 5 Sterne.", "danger")
        return redirect(url_for("bookings.detail", booking_id=booking.id))
    target = booking.flight.pilot if current_user.id == booking.passenger_id else booking.passenger
    db.session.add(Review(booking_id=booking.id, author_id=current_user.id, target_id=target.id,
                          rating=rating, comment=request.form.get("comment", "").strip()))
    notify(target, f"{current_user.short_name} hat dich mit {rating} Sternen bewertet.",
           url_for("profile.public", user_id=target.id))
    db.session.commit()
    flash("Danke für deine Bewertung!", "success")
    return redirect(url_for("bookings.detail", booking_id=booking.id))
