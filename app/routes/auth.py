from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db
from ..models import User
from ..utils import notify

bp = Blueprint("auth", __name__)


def _safe_next(target):
    if target and urlparse(target).netloc == "" and target.startswith("/") and not target.startswith("//"):
        return target
    return None


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
               url_for("profile.edit"))
        db.session.commit()
        login_user(user)
        flash(f"Willkommen an Bord, {user.first_name}!", "success")
        if form.get("as_pilot"):
            return redirect(url_for("pilot.become"))
        return redirect(_safe_next(request.args.get("next")) or url_for("main.index"))
    return render_template("auth/register.html", form=form)


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
