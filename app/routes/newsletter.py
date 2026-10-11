"""Newsletter subscription with double opt-in (GDPR-compliant proof of consent)."""
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..mailer import absolute_url, make_token, read_token, send_email
from ..models import NewsletterSubscriber, User
from ..utils import client_ip

bp = Blueprint("newsletter", __name__, url_prefix="/newsletter")

CONFIRM_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def _valid_email(email):
    return "@" in email and "." in email.split("@")[-1] and len(email) <= 255


def unsubscribe_url(sub):
    return url_for("newsletter.unsubscribe", token=make_token("newsletter-unsub", sub.id))


def request_subscription(email, user=None):
    """Create/refresh a pending subscription and send the opt-in mail. Returns the subscriber."""
    email = email.strip().lower()
    sub = NewsletterSubscriber.query.filter_by(email=email).first()
    if sub and sub.status == "confirmed":
        return sub  # already subscribed – send nothing, reveal nothing
    if sub is None:
        sub = NewsletterSubscriber(email=email)
        db.session.add(sub)
    if user is None:
        user = User.query.filter_by(email=email).first()
    sub.user_id = user.id if user else None
    sub.status = "pending"
    sub.requested_at = datetime.utcnow()
    sub.request_ip = client_ip()
    sub.confirmed_at = sub.confirm_ip = sub.unsubscribed_at = None
    db.session.commit()
    token = make_token("newsletter-confirm", {"id": sub.id, "email": sub.email})
    send_email(sub.email, "Bitte bestätige deine Newsletter-Anmeldung", "newsletter_confirm",
               action_url=url_for("newsletter.confirm", token=token), action_label="Anmeldung bestätigen")
    return sub


@bp.route("/", methods=["POST"])
def subscribe():
    email = request.form.get("email", "").strip().lower()
    if not _valid_email(email):
        flash("Bitte gib eine gültige E-Mail-Adresse an.", "danger")
    elif not request.form.get("consent"):
        flash("Bitte bestätige, dass du den Newsletter erhalten möchtest.", "danger")
    else:
        request_subscription(email)
        flash("Fast geschafft! Bitte klicke auf den Link in der E-Mail, die wir dir gerade geschickt haben.", "info")
    target = request.form.get("next", "")
    return redirect(target if target.startswith("/") and not target.startswith("//") else url_for("main.index"))


@bp.route("/bestaetigen/<token>", methods=["GET", "POST"])
def confirm(token):
    data = read_token("newsletter-confirm", token, CONFIRM_MAX_AGE)
    sub = db.session.get(NewsletterSubscriber, data["id"]) if data else None
    if not sub or sub.email != data.get("email"):
        flash("Der Bestätigungslink ist ungültig oder abgelaufen. Bitte melde dich erneut an.", "danger")
        return redirect(url_for("main.index"))
    # Confirmation needs an explicit click (POST) so link scanners in mail filters can't opt people in
    if request.method == "POST":
        if sub.status != "confirmed":
            sub.status = "confirmed"
            sub.confirmed_at = datetime.utcnow()
            sub.confirm_ip = client_ip()
            db.session.commit()
            send_email(sub.email, "Willkommen beim Skyhop-Newsletter", "newsletter_welcome",
                       unsubscribe_url=absolute_url(unsubscribe_url(sub)))
        return render_template("newsletter/status.html", state="confirmed", sub=sub)
    return render_template("newsletter/confirm.html", sub=sub, token=token)


@bp.route("/abmelden/<token>", methods=["GET", "POST"])
def unsubscribe(token):
    sub_id = read_token("newsletter-unsub", token, max_age=None)
    sub = db.session.get(NewsletterSubscriber, sub_id) if sub_id else None
    if not sub:
        flash("Ungültiger Abmeldelink.", "danger")
        return redirect(url_for("main.index"))
    if request.method == "POST":
        sub.status = "unsubscribed"
        sub.unsubscribed_at = datetime.utcnow()
        db.session.commit()
        return render_template("newsletter/status.html", state="unsubscribed", sub=sub)
    return render_template("newsletter/unsubscribe.html", sub=sub, token=token)

