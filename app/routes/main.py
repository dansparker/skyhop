from datetime import datetime

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import Favorite, Flight, Notification, Review, User

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    upcoming = (
        Flight.query.filter(Flight.status == "published", Flight.departure_time > datetime.now())
        .order_by(Flight.departure_time)
        .all()
    )
    upcoming = [f for f in upcoming if f.seats_available > 0]
    featured = upcoming[:6]
    roundtrips = [f for f in upcoming if f.flight_type == "roundtrip"][:3]
    reviews = Review.query.order_by(Review.created_at.desc()).limit(3).all()
    stats = {
        "pilots": User.query.filter_by(pilot_status="verified").count(),
        "flights": Flight.query.count(),
        "reviews": Review.query.count(),
    }
    return render_template("index.html", featured=featured, roundtrips=roundtrips, reviews=reviews, stats=stats)


@bp.route("/so-funktionierts")
def how_it_works():
    return render_template("pages/how_it_works.html")


@bp.route("/faq")
def faq():
    return render_template("pages/faq.html")


@bp.route("/sicherheit")
def safety():
    return render_template("pages/safety.html")


@bp.route("/impressum")
def imprint():
    return render_template("legal/imprint.html")


@bp.route("/datenschutz")
def privacy():
    return render_template("legal/privacy.html")


@bp.route("/agb")
def terms():
    return render_template("legal/terms.html")


@bp.route("/stornobedingungen")
def cancellation():
    return render_template("legal/cancellation.html")


@bp.route("/benachrichtigungen")
@login_required
def notifications():
    items = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(100)
        .all()
    )
    unread_ids = [n.id for n in items if not n.read]
    response = render_template("notifications.html", items=items, unread_ids=set(unread_ids))
    if unread_ids:
        Notification.query.filter(Notification.id.in_(unread_ids)).update({"read": True}, synchronize_session=False)
        db.session.commit()
    return response


@bp.route("/merkliste")
@login_required
def favorites():
    favs = Favorite.query.filter_by(user_id=current_user.id).order_by(Favorite.created_at.desc()).all()
    return render_template("favorites.html", flights=[f.flight for f in favs])


@bp.route("/merkliste/<int:flight_id>", methods=["POST"])
@login_required
def toggle_favorite(flight_id):
    flight = db.session.get(Flight, flight_id) or abort(404)
    fav = db.session.get(Favorite, (current_user.id, flight.id))
    if fav:
        db.session.delete(fav)
    else:
        db.session.add(Favorite(user_id=current_user.id, flight_id=flight.id))
    db.session.commit()
    return redirect(request.form.get("next") or url_for("flights.detail", flight_id=flight.id))


@bp.route("/dev/mails")
@bp.route("/dev/mails/<int:index>")
def dev_mails(index=None):
    """Local inbox for development: shows mails that were not sent because MAIL_SERVER is not configured."""
    if current_app.config.get("MAIL_SERVER") or not (current_app.debug or current_app.testing):
        abort(404)
    from ..mailer import outbox

    mails = list(outbox)
    if index is not None:
        if index >= len(mails):
            abort(404)
        return mails[index]["html"]
    return render_template("dev_mails.html", mails=mails)
