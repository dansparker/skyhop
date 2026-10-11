from datetime import datetime, timedelta

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import payments
from ..extensions import db
from ..models import Aircraft, Booking, Favorite, Flight, FlightWish
from ..utils import find_airport, notify, parse_datetime, parse_int, pilot_required, resolve_airports

bp = Blueprint("flights", __name__)

SORTS = {
    "date": ("Datum", lambda f: f.departure_time),
    "price": ("Preis", lambda f: f.price_per_seat),
    "seats": ("Freie Plätze", lambda f: -f.seats_available),
    "rating": ("Bewertung", lambda f: -(f.pilot.rating or 0)),
}


@bp.route("/fluege")
def search():
    args = request.args
    q_from = args.get("from", "").strip()
    q_to = args.get("to", "").strip()
    radius = parse_int(args.get("radius"), 0, 0, 500)
    seats = parse_int(args.get("seats"), 1, 1, 9)
    max_price = parse_int(args.get("max_price"), None, 0)
    flight_type = args.get("type", "")
    sort = args.get("sort", "date") if args.get("sort") in SORTS else "date"

    date_from = parse_datetime(args.get("date", ""))
    date_to = parse_datetime(args.get("date_to", ""))
    start = max(date_from or datetime.now(), datetime.now())
    if date_from and not date_to:
        end = date_from + timedelta(days=1)
    else:
        end = (date_to + timedelta(days=1)) if date_to else None

    query = Flight.query.filter(Flight.status == "published", Flight.departure_time >= start)
    if end:
        query = query.filter(Flight.departure_time < end)
    if flight_type in Flight.TYPES:
        query = query.filter(Flight.flight_type == flight_type)
    if max_price is not None:
        query = query.filter(Flight.price_per_seat <= max_price)

    dep_ids = resolve_airports(q_from, radius)
    arr_ids = resolve_airports(q_to, radius)
    if dep_ids is not None:
        query = query.filter(Flight.departure_id.in_(dep_ids or [-1]))
    if arr_ids is not None:
        query = query.filter(Flight.arrival_id.in_(arr_ids or [-1]))

    results = [f for f in query.all() if f.seats_available >= seats]
    results.sort(key=SORTS[sort][1])

    favorites = set()
    if current_user.is_authenticated:
        favorites = {f.flight_id for f in Favorite.query.filter_by(user_id=current_user.id)}

    return render_template(
        "flights/search.html",
        results=results,
        args=args,
        sorts={k: v[0] for k, v in SORTS.items()},
        sort=sort,
        types=Flight.TYPES,
        favorites=favorites,
    )


@bp.route("/fluege/<int:flight_id>")
def detail(flight_id):
    flight = db.session.get(Flight, flight_id) or abort(404)
    if flight.status == "cancelled" and (not current_user.is_authenticated or current_user.id != flight.pilot_id):
        flash("Dieser Flug wurde abgesagt.", "warning")
    my_booking = None
    is_favorite = False
    if current_user.is_authenticated:
        my_booking = (
            Booking.query.filter_by(flight_id=flight.id, passenger_id=current_user.id)
            .filter(Booking.status.in_(("pending", "accepted", "paid", "completed")))
            .first()
        )
        is_favorite = db.session.get(Favorite, (current_user.id, flight.id)) is not None
    similar = (
        Flight.query.filter(
            Flight.id != flight.id,
            Flight.status == "published",
            Flight.departure_time > datetime.now(),
            Flight.departure_id == flight.departure_id,
        )
        .order_by(Flight.departure_time)
        .limit(3)
        .all()
    )
    fee_rate = current_app.config["SERVICE_FEE_RATE"]
    return render_template(
        "flights/detail.html",
        flight=flight,
        my_booking=my_booking,
        is_favorite=is_favorite,
        similar=similar,
        fee_rate=fee_rate,
    )


def _flight_from_form(form, flight=None):
    """Validate the flight form. Returns (data dict, errors list)."""
    errors = []
    aircraft = db.session.get(Aircraft, parse_int(form.get("aircraft_id"), 0))
    if not aircraft or aircraft.owner_id != current_user.id:
        errors.append("Bitte wähle eines deiner Flugzeuge.")
    flight_type = form.get("flight_type")
    if flight_type not in Flight.TYPES:
        errors.append("Ungültige Flugart.")
    dep = find_airport(form.get("departure"))
    if not dep:
        errors.append("Abflugplatz nicht gefunden.")
    if flight_type == "roundtrip":
        arr = dep
    else:
        arr = find_airport(form.get("arrival"))
        if not arr:
            errors.append("Zielflugplatz nicht gefunden.")
        elif dep and arr.id == dep.id:
            errors.append("Abflug und Ziel sind identisch – wähle stattdessen „Rundflug“.")
    departure_time = parse_datetime(form.get("date"), form.get("time"))
    if not departure_time:
        errors.append("Bitte gib Datum und Uhrzeit an.")
    elif departure_time < datetime.now():
        errors.append("Der Abflug muss in der Zukunft liegen.")
    return_time = None
    if flight_type == "daytrip":
        return_time = parse_datetime(form.get("return_date") or form.get("date"), form.get("return_time"))
        if not return_time or (departure_time and return_time <= departure_time):
            errors.append("Bitte gib eine Rückflugzeit nach dem Abflug an.")
    duration = parse_int(form.get("duration_minutes"), None, 10, 1440)
    if not duration:
        errors.append("Bitte gib eine Flugdauer zwischen 10 und 1440 Minuten an.")
    seats = parse_int(form.get("seats_total"), None, 1, 20)
    if not seats:
        errors.append("Bitte gib die Anzahl freier Plätze an.")
    elif aircraft and seats > aircraft.seats:
        errors.append(f"Dein Flugzeug hat nur {aircraft.seats} Passagierplätze.")
    if flight and seats and seats < flight.seats_booked:
        errors.append(f"Es sind bereits {flight.seats_booked} Plätze gebucht.")
    cost = parse_int(form.get("direct_cost"), None, 1, 100000)
    if not cost:
        errors.append("Bitte gib die direkten Kosten des Flugs an.")
    title = form.get("title", "").strip()
    if not title:
        errors.append("Bitte gib einen Titel an.")
    data = dict(
        aircraft_id=aircraft.id if aircraft else None,
        flight_type=flight_type,
        departure_id=dep.id if dep else None,
        arrival_id=arr.id if arr else None,
        departure_time=departure_time,
        return_time=return_time,
        duration_minutes=duration,
        seats_total=seats,
        direct_cost=cost,
        price_per_seat=Flight.calc_price(cost or 0, seats or 1),
        title=title[:160],
        description=form.get("description", "").strip(),
        meeting_point=form.get("meeting_point", "").strip()[:200],
    )
    return data, errors


def _notify_matching_wishes(flight):
    wishes = FlightWish.query.filter(
        FlightWish.active.is_(True),
        FlightWish.departure_id == flight.departure_id,
        FlightWish.date_from <= flight.departure_time.date(),
        FlightWish.date_to >= flight.departure_time.date(),
        FlightWish.user_id != flight.pilot_id,
    ).all()
    for w in wishes:
        if w.arrival_id and w.arrival_id != flight.arrival_id:
            continue
        notify(w.user, f"Neuer Flug passend zu deinem Flugwunsch: {flight.route_label}",
               url_for("flights.detail", flight_id=flight.id))


@bp.route("/fluege/neu", methods=["GET", "POST"])
@pilot_required
def create():
    if not current_user.aircraft:
        flash("Lege zuerst ein Flugzeug an, bevor du einen Flug anbietest.", "info")
        return redirect(url_for("pilot.aircraft_new", next=url_for("flights.create")))
    if request.method == "POST":
        data, errors = _flight_from_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("flights/form.html", form=request.form, flight=None, types=Flight.TYPES)
        flight = Flight(pilot_id=current_user.id, **data)
        db.session.add(flight)
        db.session.flush()
        _notify_matching_wishes(flight)
        db.session.commit()
        flash("Dein Flug ist jetzt online! 🛩️", "success")
        return redirect(url_for("flights.detail", flight_id=flight.id))
    form = {"date": (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"), "time": "10:00",
            "flight_type": request.args.get("type", "trip"),
            "departure": current_user.home_airport.label if current_user.home_airport else ""}
    return render_template("flights/form.html", form=form, flight=None, types=Flight.TYPES)


@bp.route("/fluege/<int:flight_id>/bearbeiten", methods=["GET", "POST"])
@pilot_required
def edit(flight_id):
    flight = db.session.get(Flight, flight_id) or abort(404)
    if flight.pilot_id != current_user.id:
        abort(403)
    if flight.status != "published" or flight.is_past:
        flash("Dieser Flug kann nicht mehr bearbeitet werden.", "warning")
        return redirect(url_for("flights.detail", flight_id=flight.id))
    if request.method == "POST":
        data, errors = _flight_from_form(request.form, flight)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("flights/form.html", form=request.form, flight=flight, types=Flight.TYPES)
        for k, v in data.items():
            setattr(flight, k, v)
        for b in flight.bookings:
            if b.status in ("pending", "accepted", "paid"):
                notify(b.passenger, f"Der Flug „{flight.title}“ wurde vom Piloten aktualisiert.",
                       url_for("flights.detail", flight_id=flight.id))
        db.session.commit()
        flash("Flug aktualisiert.", "success")
        return redirect(url_for("flights.detail", flight_id=flight.id))
    form = {
        "title": flight.title, "flight_type": flight.flight_type, "aircraft_id": str(flight.aircraft_id),
        "departure": flight.departure.label, "arrival": flight.arrival.label,
        "date": flight.departure_time.strftime("%Y-%m-%d"), "time": flight.departure_time.strftime("%H:%M"),
        "return_date": flight.return_time.strftime("%Y-%m-%d") if flight.return_time else "",
        "return_time": flight.return_time.strftime("%H:%M") if flight.return_time else "",
        "duration_minutes": flight.duration_minutes, "seats_total": flight.seats_total,
        "direct_cost": flight.direct_cost, "description": flight.description or "",
        "meeting_point": flight.meeting_point or "",
    }
    return render_template("flights/form.html", form=form, flight=flight, types=Flight.TYPES)


@bp.route("/fluege/<int:flight_id>/absagen", methods=["POST"])
@login_required
def cancel(flight_id):
    flight = db.session.get(Flight, flight_id) or abort(404)
    if flight.pilot_id != current_user.id and not current_user.is_admin:
        abort(403)
    if flight.status != "published":
        abort(400)
    flight.status = "cancelled"
    reason = request.form.get("reason", "").strip()
    for b in flight.bookings:
        if b.status in ("pending", "accepted", "paid"):
            was_paid = b.status == "paid"
            b.status = "cancelled"
            text = f"Der Flug „{flight.title}“ am {flight.departure_time:%d.%m.%Y} wurde abgesagt."
            if was_paid:
                payments.refund(b)
                text += f" Du erhältst {b.total_price} € vollständig zurück."
            if reason:
                text += f" Grund: {reason[:120]}"
            notify(b.passenger, text, url_for("bookings.detail", booking_id=b.id))
    db.session.commit()
    flash("Der Flug wurde abgesagt. Alle Passagiere wurden informiert.", "info")
    return redirect(url_for("bookings.dashboard", tab="pilot"))


@bp.route("/fluege/<int:flight_id>/abschliessen", methods=["POST"])
@login_required
def complete(flight_id):
    flight = db.session.get(Flight, flight_id) or abort(404)
    if flight.pilot_id != current_user.id:
        abort(403)
    if flight.status != "published" or not flight.is_past:
        flash("Ein Flug kann erst nach dem Abflug als durchgeführt markiert werden.", "warning")
        return redirect(url_for("flights.detail", flight_id=flight.id))
    flight.status = "completed"
    for b in flight.bookings:
        if b.status == "paid":
            b.status = "completed"
            notify(b.passenger, f"Wie war dein Flug mit {flight.pilot.first_name}? Gib jetzt eine Bewertung ab.",
                   url_for("bookings.detail", booking_id=b.id))
        elif b.status in ("pending", "accepted"):
            b.status = "cancelled"
    db.session.commit()
    flash("Flug als durchgeführt markiert. Die Auszahlung wird veranlasst.", "success")
    return redirect(url_for("bookings.dashboard", tab="pilot"))
