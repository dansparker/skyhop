import time
from datetime import datetime
from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db
from ..mailer import make_token, read_token, send_email
from ..models import User
from ..utils import notify

bp = Blueprint("auth", __name__)

CONFIRM_MAX_AGE = 60 * 60 * 48   # 48 h
RESET_MAX_AGE = 60 * 60          # 1 h
RESEND_COOLDOWN = 60             # seconds


def _safe_next(target):
    if target and urlparse(target).netloc == "" and target.startswith("/") and not target.startswith("//"):
        return target
    return None


def send_confirmation_email(user):
    token = make_token("email-confirm", {"id": user.id, "email": user.email})
    send_email(user.email, "Bitte bestätige deine E-Mail-Adresse", "confirm_email",
               action_url=url_for("auth.confirm_email", token=token), action_label="E-Mail-Adresse bestätigen",
               user=user)


@bp.route("/registrieren", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = request.form
    if request.method == "POST":
        email = form.get("email", "").strip().lower()
        first = form.get("first_name", "").strip()
        last = form.get("last_name", "").strip()
        password = form.get("password", "")
        errors = []
        if not first or not last:
            errors.append("Bitte gib Vor- und Nachnamen an.")
        if "@" not in email or "." not in email.split("@")[-1]:
            errors.append("Bitte gib eine gültige E-Mail-Adresse an.")
        if len(password) < 8:
            errors.append("Das Passwort muss mindestens 8 Zeichen lang sein.")
        if password != form.get("password2", ""):
            errors.append("Die Passwörter stimmen nicht überein.")
        if not form.get("terms"):
            errors.append("Bitte akzeptiere die Nutzungsbedingungen.")
        if User.query.filter_by(email=email).first():
            errors.append("Für diese E-Mail-Adresse existiert bereits ein Konto.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("auth/register.html", form=form)
        user = User(email=email, first_name=first, last_name=last, city=form.get("city", "").strip() or None)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        notify(user, "Willkommen bei Skyhop! Vervollständige dein Profil, damit Pilot:innen dich kennenlernen.",
               url_for("profile.edit"), email=False)
        db.session.commit()
        send_confirmation_email(user)
        session["confirm_sent_at"] = time.time()
        if form.get("newsletter"):
            from .newsletter import request_subscription

            request_subscription(user.email, user=user)
        login_user(user)
        flash(f"Willkommen an Bord, {user.first_name}! Wir haben dir eine E-Mail geschickt – "
              "bitte bestätige deine Adresse, um Flüge buchen zu können.", "success")
        if form.get("as_pilot"):
            return redirect(url_for("pilot.become"))
        return redirect(_safe_next(request.args.get("next")) or url_for("main.index"))
    return render_template("auth/register.html", form=form)


@bp.route("/email-bestaetigen/<token>")
def confirm_email(token):
    data = read_token("email-confirm", token, CONFIRM_MAX_AGE)
    user = db.session.get(User, data["id"]) if data else None
    if not user or user.email != data.get("email"):
        flash("Der Bestätigungslink ist ungültig oder abgelaufen. Fordere einfach einen neuen an.", "danger")
        return redirect(url_for("auth.unconfirmed") if current_user.is_authenticated else url_for("auth.login"))
    if not user.email_confirmed:
        user.email_confirmed = True
        user.email_confirmed_at = datetime.utcnow()
        db.session.commit()
        flash("Danke! Deine E-Mail-Adresse ist bestätigt. 🎉", "success")
    else:
        flash("Deine E-Mail-Adresse war bereits bestätigt.", "info")
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    return redirect(url_for("bookings.dashboard"))


@bp.route("/email-bestaetigen", methods=["GET", "POST"])
@login_required
def unconfirmed():
    if current_user.email_confirmed:
        return redirect(url_for("bookings.dashboard"))
    if request.method == "POST":
        last = session.get("confirm_sent_at", 0)
        if time.time() - last < RESEND_COOLDOWN:
            flash("Bitte warte eine Minute, bevor du erneut eine E-Mail anforderst.", "warning")
        else:
            send_confirmation_email(current_user)
            session["confirm_sent_at"] = time.time()
            flash(f"Wir haben eine neue Bestätigungs-E-Mail an {current_user.email} gesendet.", "success")
        return redirect(url_for("auth.unconfirmed"))
    return render_template("auth/unconfirmed.html")


@bp.route("/anmelden", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(request.form.get("password", "")):
            login_user(user, remember=bool(request.form.get("remember")))
            flash(f"Schön, dass du da bist, {user.first_name}!", "success")
            return redirect(_safe_next(request.args.get("next")) or url_for("bookings.dashboard"))
        flash("E-Mail oder Passwort ist falsch.", "danger")
    return render_template("auth/login.html")


@bp.route("/abmelden", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Du wurdest abgemeldet.", "info")
    return redirect(url_for("main.index"))


@bp.route("/passwort", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        if not current_user.check_password(request.form.get("current", "")):
            flash("Das aktuelle Passwort ist falsch.", "danger")
        elif len(request.form.get("new", "")) < 8:
            flash("Das neue Passwort muss mindestens 8 Zeichen lang sein.", "danger")
        elif request.form.get("new") != request.form.get("new2"):
            flash("Die neuen Passwörter stimmen nicht überein.", "danger")
        else:
            current_user.set_password(request.form["new"])
            db.session.commit()
            flash("Passwort geändert.", "success")
            return redirect(url_for("profile.edit"))
    return render_template("auth/password.html")


def _reset_fingerprint(user):
    # Token becomes invalid as soon as the password changes (single use)
    return user.password_hash[-16:]


@bp.route("/passwort-vergessen", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            token = make_token("password-reset", {"id": user.id, "fp": _reset_fingerprint(user)})
            send_email(user.email, "Passwort zurücksetzen", "reset_password",
                       action_url=url_for("auth.reset_password", token=token), action_label="Neues Passwort festlegen",
                       user=user)
        # Same answer either way – does not reveal whether an account exists
        flash("Falls ein Konto mit dieser Adresse existiert, haben wir dir einen Link zum Zurücksetzen geschickt.",
              "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot_password.html")


@bp.route("/passwort-zuruecksetzen/<token>", methods=["GET", "POST"])
def reset_password(token):
    data = read_token("password-reset", token, RESET_MAX_AGE)
    user = db.session.get(User, data["id"]) if data else None
    if not user or data.get("fp") != _reset_fingerprint(user):
        flash("Der Link ist ungültig oder abgelaufen. Bitte fordere einen neuen an.", "danger")
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        pw = request.form.get("new", "")
        if len(pw) < 8:
            flash("Das Passwort muss mindestens 8 Zeichen lang sein.", "danger")
        elif pw != request.form.get("new2"):
            flash("Die Passwörter stimmen nicht überein.", "danger")
        else:
            user.set_password(pw)
            # Clicking a link from the inbox also proves ownership of the address
            if not user.email_confirmed:
                user.email_confirmed = True
                user.email_confirmed_at = datetime.utcnow()
            db.session.commit()
            flash("Dein Passwort wurde geändert. Du kannst dich jetzt anmelden.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset_password.html")
