from datetime import datetime
from functools import wraps

from flask import abort, flash, redirect, url_for
from flask_login import current_user

from .extensions import db
from .models import Airport, Conversation, Notification


def notify(user, text, link=None, email=True):
    """In-app notification, mirrored by e-mail if the user confirmed their address and wants mails."""
    db.session.add(Notification(user_id=user.id, text=text, link=link))
    if email and user.email_confirmed and user.email_notifications:
        from .mailer import send_email

        subject = text if len(text) <= 70 else text[:67].rstrip() + "…"
        send_email(user.email, subject, "notification", action_url=link, action_label="Auf Skyhop ansehen",
                   user=user, text=text)


def confirmed_required(view):
    """Double opt-in: actions that contact other people require a confirmed e-mail address."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not current_user.email_confirmed:
            flash("Bitte bestätige zuerst deine E-Mail-Adresse – wir haben dir einen Link geschickt.", "warning")
            return redirect(url_for("auth.unconfirmed"))
        return view(*args, **kwargs)
    return wrapped


def client_ip():
    from flask import request

    # Behind a reverse proxy set TRUST_PROXY=1 (ProxyFix), so remote_addr is the real client IP
    return (request.remote_addr or "")[:64]


def pilot_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not current_user.email_confirmed:
            flash("Bitte bestätige zuerst deine E-Mail-Adresse.", "warning")
            return redirect(url_for("auth.unconfirmed"))
        if not current_user.is_pilot:
            flash("Diese Funktion steht nur verifizierten Pilot:innen zur Verfügung.", "warning")
            return redirect(url_for("pilot.become"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def find_airport(value):
    """Resolve user input like 'LOWW', 'LOWW – Wien (...)' or 'Wien' to one airport."""
    if not value:
        return None
    value = value.strip()
    code = value.split(" ")[0].upper()
    if len(code) == 4 and code.isalpha():
        ap = Airport.query.filter_by(icao=code).first()
        if ap:
            return ap
    like = f"%{value}%"
    return Airport.query.filter(
        db.or_(Airport.city.ilike(like), Airport.name.ilike(like))
    ).order_by(Airport.city).first()


def resolve_airports(query, radius_km=0):
    """Return set of airport ids matching a free-text query (optionally within a radius)."""
    if not query:
        return None
    query = query.strip()
    code = query.split(" ")[0].upper()
    matches = []
    if len(code) == 4 and code.isalpha():
        matches = Airport.query.filter_by(icao=code).all()
    if not matches:
        like = f"%{query}%"
        matches = Airport.query.filter(
            db.or_(Airport.city.ilike(like), Airport.name.ilike(like), Airport.icao.ilike(like))
        ).all()
    ids = {a.id for a in matches}
    if radius_km and matches:
        for ap in Airport.query.all():
            if any(ap.distance_to(m) <= radius_km for m in matches):
                ids.add(ap.id)
    return ids


def get_or_create_conversation(user_a, user_b, flight=None):
    q = Conversation.query.filter(
        db.or_(
            db.and_(Conversation.user1_id == user_a.id, Conversation.user2_id == user_b.id),
            db.and_(Conversation.user1_id == user_b.id, Conversation.user2_id == user_a.id),
        )
    )
    if flight is not None:
        q = q.filter(Conversation.flight_id == flight.id)
    conv = q.first()
    if conv is None:
        conv = Conversation(user1_id=user_a.id, user2_id=user_b.id, flight_id=flight.id if flight else None)
        db.session.add(conv)
        db.session.flush()
    return conv


def parse_datetime(date_str, time_str="00:00"):
    try:
        return datetime.strptime(f"{date_str} {time_str or '00:00'}", "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return None


def parse_int(value, default=None, minimum=None, maximum=None):
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None and v < minimum:
        return default
    if maximum is not None and v > maximum:
        return default
    return v
