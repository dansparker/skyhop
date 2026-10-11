from datetime import date, datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import FlightWish
from ..utils import find_airport, parse_int

bp = Blueprint("wishes", __name__, url_prefix="/flugwuensche")


@bp.route("/")
def index():
    wishes = (
        FlightWish.query.filter(FlightWish.active.is_(True), FlightWish.date_to >= date.today())
        .order_by(FlightWish.date_from)
        .all()
    )
    q = request.args.get("q", "").strip().lower()
    if q:
        wishes = [w for w in wishes if q in w.departure.city.lower() or q in w.departure.icao.lower()
                  or (w.arrival and (q in w.arrival.city.lower() or q in w.arrival.icao.lower()))]
    mine = []
    if current_user.is_authenticated:
        mine = FlightWish.query.filter_by(user_id=current_user.id).order_by(FlightWish.created_at.desc()).all()
    return render_template("wishes/index.html", wishes=wishes, mine=mine, q=q)


@bp.route("/neu", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        f = request.form
        dep = find_airport(f.get("departure"))
        arr = find_airport(f.get("arrival")) if f.get("arrival", "").strip() else None
        errors = []
        try:
            d_from = datetime.strptime(f.get("date_from", ""), "%Y-%m-%d").date()
            d_to = datetime.strptime(f.get("date_to", ""), "%Y-%m-%d").date()
            if d_to < d_from:
                errors.append("Das Enddatum liegt vor dem Startdatum.")
            if d_to < date.today():
                errors.append("Der Zeitraum liegt in der Vergangenheit.")
        except ValueError:
            errors.append("Bitte gib einen gültigen Zeitraum an.")
            d_from = d_to = None
        if not dep:
            errors.append("Abflugort nicht gefunden.")
        if f.get("arrival", "").strip() and not arr:
            errors.append("Zielort nicht gefunden.")
        seats = parse_int(f.get("seats"), None, 1, 9)
        if not seats:
            errors.append("Bitte gib 1–9 Plätze an.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("wishes/form.html", form=f)
        wish = FlightWish(user_id=current_user.id, departure_id=dep.id, arrival_id=arr.id if arr else None,
                          date_from=d_from, date_to=d_to, seats=seats,
                          budget_per_seat=parse_int(f.get("budget_per_seat"), None, 0),
                          message=f.get("message", "").strip())
        db.session.add(wish)
        db.session.commit()
        flash("Dein Flugwunsch ist online. Wir benachrichtigen dich, wenn ein passender Flug angeboten wird.",
              "success")
        return redirect(url_for("wishes.index"))
    return render_template("wishes/form.html", form={})


@bp.route("/<int:wish_id>/beenden", methods=["POST"])
@login_required
def close(wish_id):
    wish = db.session.get(FlightWish, wish_id) or abort(404)
    if wish.user_id != current_user.id:
        abort(403)
    wish.active = False
    db.session.commit()
    flash("Flugwunsch beendet.", "info")
    return redirect(url_for("wishes.index"))
