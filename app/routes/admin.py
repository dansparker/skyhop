from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Booking, Flight, Review, User
from ..utils import admin_required, notify

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/")
@admin_required
def index():
    paid = Booking.query.filter(Booking.status.in_(("paid", "completed"))).all()
    stats = {
        "users": User.query.count(),
        "pilots": User.query.filter_by(pilot_status="verified").count(),
        "pending_pilots": User.query.filter_by(pilot_status="pending").count(),
        "flights": Flight.query.filter(Flight.status == "published", Flight.departure_time > datetime.now()).count(),
        "bookings": len(paid),
        "volume": sum(b.total_price for b in paid),
        "fees": sum(b.service_fee for b in paid),
        "reviews": Review.query.count(),
    }
    latest_bookings = Booking.query.order_by(Booking.created_at.desc()).limit(10).all()
    return render_template("admin/index.html", stats=stats, latest_bookings=latest_bookings)


@bp.route("/piloten")
@admin_required
def pilots():
    pending = User.query.filter_by(pilot_status="pending").order_by(User.created_at).all()
    verified = User.query.filter_by(pilot_status="verified").order_by(User.last_name).all()
    return render_template("admin/pilots.html", pending=pending, verified=verified)


@bp.route("/piloten/<int:user_id>/<action>", methods=["POST"])
@admin_required
def pilot_action(user_id, action):
    user = db.session.get(User, user_id) or abort(404)
    if action == "approve":
        user.pilot_status = "verified"
        notify(user, "Deine Pilotenlizenz wurde verifiziert! Du kannst jetzt Flüge anbieten.",
               url_for("flights.create"))
        flash(f"{user.name} ist jetzt verifiziert.", "success")
    elif action == "reject":
        user.pilot_status = "rejected"
        notify(user, "Deine Pilotenverifizierung konnte nicht bestätigt werden. Bitte prüfe deine Angaben.",
               url_for("pilot.become"))
        flash(f"Verifizierung von {user.name} abgelehnt.", "info")
    else:
        abort(400)
    db.session.commit()
    return redirect(url_for("admin.pilots"))


@bp.route("/nutzer")
@admin_required
def users():
    q = request.args.get("q", "").strip()
    query = User.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(User.email.ilike(like), User.first_name.ilike(like), User.last_name.ilike(like)))
    return render_template("admin/users.html", users=query.order_by(User.created_at.desc()).all(), q=q)


@bp.route("/fluege")
@admin_required
def flights():
    items = Flight.query.order_by(Flight.departure_time.desc()).all()
    return render_template("admin/flights.html", flights=items)
