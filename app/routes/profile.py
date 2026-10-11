import json
from datetime import datetime

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user

from .. import account

from ..extensions import db
from ..models import Flight, NewsletterSubscriber, Payout, User
from ..utils import find_airport
from .newsletter import request_subscription

bp = Blueprint("profile", __name__)


@bp.route("/profil/<int:user_id>")
def public(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if user.is_deleted:
        abort(404)
    upcoming = (
        Flight.query.filter(Flight.pilot_id == user.id, Flight.status == "published",
                            Flight.departure_time > datetime.now())
        .order_by(Flight.departure_time)
        .all()
    )
    return render_template("profile/public.html", user=user, upcoming=upcoming)


@bp.route("/profil", methods=["GET", "POST"])
@login_required
def edit():
    if request.method == "POST":
        f = request.form
        first = f.get("first_name", "").strip()
        last = f.get("last_name", "").strip()
        if not first or not last:
            flash("Vor- und Nachname dürfen nicht leer sein.", "danger")
            return render_template("profile/edit.html", form=f, newsletter=None)
        current_user.first_name = first
        current_user.last_name = last
        current_user.city = f.get("city", "").strip() or None
        current_user.phone = f.get("phone", "").strip() or None
        current_user.bio = f.get("bio", "").strip() or None
        current_user.email_notifications = bool(f.get("email_notifications"))
        sub = NewsletterSubscriber.query.filter_by(email=current_user.email).first()
        wants_newsletter = bool(f.get("newsletter"))
        if wants_newsletter and (not sub or sub.status == "unsubscribed"):
            request_subscription(current_user.email, user=current_user)
            flash("Bitte bestätige deine Newsletter-Anmeldung über den Link in der E-Mail.", "info")
        elif not wants_newsletter and sub and sub.status in ("pending", "confirmed"):
            sub.status = "unsubscribed"
            sub.unsubscribed_at = datetime.utcnow()
        if current_user.pilot_status != "none":
            home = find_airport(f.get("home_airport"))
            current_user.home_airport_id = home.id if home else None
        db.session.commit()
        flash("Profil gespeichert.", "success")
        return redirect(url_for("profile.edit"))
    form = {
        "first_name": current_user.first_name, "last_name": current_user.last_name,
        "city": current_user.city or "", "phone": current_user.phone or "", "bio": current_user.bio or "",
        "home_airport": current_user.home_airport.label if current_user.home_airport else "",
        "email_notifications": current_user.email_notifications,
    }
    sub = NewsletterSubscriber.query.filter_by(email=current_user.email).first()
    return render_template("profile/edit.html", form=form, newsletter=sub)


@bp.route("/profil/daten-export")
@login_required
def data_export():
    """GDPR Art. 15/20: download all personal data as JSON."""
    data = account.export_data(current_user)
    body = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(body, mimetype="application/json",
                    headers={"Content-Disposition": f"attachment; filename=skyhop-daten-{current_user.id}.json",
                             "Cache-Control": "private, no-store"})


@bp.route("/profil/loeschen", methods=["GET", "POST"])
@login_required
def delete():
    """GDPR Art. 17: delete (anonymise) the account after password confirmation."""
    open_payouts = Payout.query.filter(Payout.pilot_id == current_user.id, Payout.status != "paid").count()
    if request.method == "POST":
        if not current_user.check_password(request.form.get("password", "")):
            flash("Das Passwort ist falsch.", "danger")
            return redirect(url_for("profile.delete"))
        if request.form.get("confirm") != "LÖSCHEN":
            flash("Bitte tippe LÖSCHEN zur Bestätigung ein.", "danger")
            return redirect(url_for("profile.delete"))
        user = current_user._get_current_object()
        logout_user()
        account.delete_account(user)
        flash("Dein Konto wurde gelöscht. Schade, dass du gehst – guten Flug! ✈️", "info")
        return redirect(url_for("main.index"))
    return render_template("profile/delete.html", open_payouts=open_payouts)
