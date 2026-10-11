from datetime import datetime

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import Booking, Flight, Review
from ..utils import get_or_create_conversation, notify, parse_int

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
@login_required
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
    notify(flight.pilot, f"{current_user.short_name} möchte {seats} Platz/Plätze für „{flight.title}“ buchen.",
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
        booking.status = "paid"
        booking.paid_at = datetime.utcnow()
        notify(booking.flight.pilot,
               f"{current_user.short_name} hat {booking.seats} Platz/Plätze für „{booking.flight.title}“ bezahlt.",
               url_for("bookings.detail", booking_id=booking.id))
        db.session.commit()
        flash("Zahlung erfolgreich – du fliegst mit! ✈️", "success")
        return redirect(url_for("bookings.detail", booking_id=booking.id))
    return render_template("bookings/checkout.html", booking=booking, flight=booking.flight)


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
    notify(booking.flight.pilot, f"{current_user.short_name} hat die Buchung für „{booking.flight.title}“ storniert.",
           url_for("flights.detail", flight_id=booking.flight_id))
    db.session.commit()
    msg = "Buchung storniert."
    if was_paid:
        msg += f" Die Erstattung über {booking.total_price} € wird veranlasst."
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
