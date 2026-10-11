import stripe
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import payouts as payout_service
from ..extensions import db
from ..models import Aircraft, Flight, Payout, User
from ..utils import find_airport, notify, parse_int, pilot_required

bp = Blueprint("pilot", __name__, url_prefix="/pilot")

LICENSES = {
    "LAPL": "LAPL(A) – Light Aircraft Pilot Licence",
    "PPL": "PPL(A) – Private Pilot Licence",
    "CPL": "CPL(A) – Commercial Pilot Licence",
    "ATPL": "ATPL(A) – Airline Transport Pilot Licence",
    "PPL-H": "PPL(H) – Hubschrauber",
}


@bp.route("/werden", methods=["GET", "POST"])
@login_required
def become():
    if request.method == "POST":
        license_type = request.form.get("license_type")
        number = request.form.get("license_number", "").strip()
        hours = parse_int(request.form.get("flight_hours"), None, 0, 100000)
        home = find_airport(request.form.get("home_airport"))
        errors = []
        if license_type not in LICENSES:
            errors.append("Bitte wähle deine Lizenz.")
        if len(number) < 4:
            errors.append("Bitte gib deine Lizenznummer an.")
        if hours is None:
            errors.append("Bitte gib deine Flugstunden an.")
        if not request.form.get("medical"):
            errors.append("Ein gültiges Medical ist Voraussetzung.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("pilot/become.html", licenses=LICENSES, form=request.form)
        current_user.license_type = license_type
        current_user.license_number = number
        current_user.flight_hours = hours
        current_user.home_airport_id = home.id if home else None
        current_user.pilot_status = "pending"
        for admin in User.query.filter_by(is_admin=True):
            notify(admin, f"Neue Pilotenverifizierung: {current_user.name}", url_for("admin.pilots"))
        db.session.commit()
        flash("Danke! Wir prüfen deine Lizenz – meist innerhalb von 24 Stunden.", "success")
        return redirect(url_for("pilot.become"))
    form = {
        "license_type": current_user.license_type or "",
        "license_number": current_user.license_number or "",
        "flight_hours": current_user.flight_hours or "",
        "home_airport": current_user.home_airport.label if current_user.home_airport else "",
    }
    return render_template("pilot/become.html", licenses=LICENSES, form=form)


@bp.route("/flugzeuge")
@pilot_required
def aircraft_list():
    return render_template("pilot/aircraft_list.html", aircraft=current_user.aircraft)


def _aircraft_from_form(form):
    errors = []
    reg = form.get("registration", "").strip().upper()
    if len(reg) < 3:
        errors.append("Bitte gib das Kennzeichen an (z. B. OE-KAB).")
    if not form.get("manufacturer", "").strip() or not form.get("model", "").strip():
        errors.append("Bitte gib Hersteller und Modell an.")
    seats = parse_int(form.get("seats"), None, 1, 20)
    if not seats:
        errors.append("Bitte gib die Anzahl der Passagierplätze (1–20) an.")
    data = dict(
        registration=reg,
        manufacturer=form.get("manufacturer", "").strip(),
        model=form.get("model", "").strip(),
        seats=seats,
        cruise_speed_kt=parse_int(form.get("cruise_speed_kt"), 110, 40, 400),
        year=parse_int(form.get("year"), None, 1900, 2100),
        description=form.get("description", "").strip(),
    )
    return data, errors


@bp.route("/flugzeuge/neu", methods=["GET", "POST"])
@pilot_required
def aircraft_new():
    if request.method == "POST":
        data, errors = _aircraft_from_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("pilot/aircraft_form.html", form=request.form, aircraft=None)
        db.session.add(Aircraft(owner_id=current_user.id, **data))
        db.session.commit()
        flash("Flugzeug gespeichert.", "success")
        nxt = request.args.get("next")
        if nxt and nxt.startswith("/") and not nxt.startswith("//"):
            return redirect(nxt)
        return redirect(url_for("pilot.aircraft_list"))
    return render_template("pilot/aircraft_form.html", form={}, aircraft=None)


@bp.route("/flugzeuge/<int:aircraft_id>", methods=["GET", "POST"])
@pilot_required
def aircraft_edit(aircraft_id):
    aircraft = db.session.get(Aircraft, aircraft_id) or abort(404)
    if aircraft.owner_id != current_user.id:
        abort(403)
    if request.method == "POST":
        data, errors = _aircraft_from_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("pilot/aircraft_form.html", form=request.form, aircraft=aircraft)
        for k, v in data.items():
            setattr(aircraft, k, v)
        db.session.commit()
        flash("Flugzeug aktualisiert.", "success")
        return redirect(url_for("pilot.aircraft_list"))
    form = {c: getattr(aircraft, c) for c in
            ("registration", "manufacturer", "model", "seats", "cruise_speed_kt", "year", "description")}
    return render_template("pilot/aircraft_form.html", form=form, aircraft=aircraft)


@bp.route("/flugzeuge/<int:aircraft_id>/loeschen", methods=["POST"])
@pilot_required
def aircraft_delete(aircraft_id):
    aircraft = db.session.get(Aircraft, aircraft_id) or abort(404)
    if aircraft.owner_id != current_user.id:
        abort(403)
    if Flight.query.filter_by(aircraft_id=aircraft.id).first():
        flash("Dieses Flugzeug ist mit Flügen verknüpft und kann nicht gelöscht werden.", "warning")
    else:
        db.session.delete(aircraft)
        db.session.commit()
        flash("Flugzeug gelöscht.", "info")
    return redirect(url_for("pilot.aircraft_list"))


# --- Payouts -----------------------------------------------------------------------------------------

@bp.route("/auszahlungen", methods=["GET", "POST"])
@pilot_required
def payouts():
    methods = payout_service.available_methods()
    if request.method == "POST":
        method = request.form.get("payout_method")
        country = request.form.get("payout_country", "").upper()
        if country in payout_service.COUNTRIES:
            current_user.payout_country = country
        if method == "paypal" and "paypal" in methods:
            email = request.form.get("paypal_payout_email", "").strip().lower()
            if "@" not in email or "." not in email.split("@")[-1]:
                flash("Bitte gib die E-Mail-Adresse deines PayPal-Kontos an.", "danger")
                return redirect(url_for("pilot.payouts"))
            current_user.payout_method = "paypal"
            current_user.paypal_payout_email = email
            db.session.commit()
            flash("PayPal als Auszahlungsweg gespeichert.", "success")
            _retry_waiting(current_user)
        elif method == "stripe" and "stripe" in methods:
            current_user.payout_method = "stripe"
            db.session.commit()
            return redirect(url_for("pilot.stripe_onboarding"), code=307)
        return redirect(url_for("pilot.payouts"))

    if request.args.get("stripe") == "zurueck" and current_user.stripe_account_id:
        try:
            if payout_service.refresh_stripe_status(current_user):
                flash("Dein Stripe-Konto ist eingerichtet – Auszahlungen sind aktiv. 🎉", "success")
                _retry_waiting(current_user)
            else:
                flash("Die Einrichtung bei Stripe ist noch nicht abgeschlossen.", "warning")
        except stripe.StripeError:
            current_app.logger.exception("Stripe-Status für Nutzer %s nicht abrufbar", current_user.id)
    items = Payout.query.filter_by(pilot_id=current_user.id).order_by(Payout.created_at.desc()).all()
    totals = {
        "paid": sum(p.amount for p in items if p.status == "paid"),
        "open": sum(p.amount for p in items if p.status != "paid"),
    }
    return render_template("pilot/payouts.html", payouts=items, totals=totals, methods=methods,
                           countries=payout_service.COUNTRIES, ready=payout_service.pilot_ready(current_user))


@bp.route("/auszahlungen/stripe", methods=["GET", "POST"])
@pilot_required
def stripe_onboarding():
    """POST: start onboarding (creates the Express account once). GET: Stripe's refresh_url for expired links."""
    if "stripe" not in payout_service.available_methods():
        abort(404)
    if request.method == "GET" and not current_user.stripe_account_id:
        return redirect(url_for("pilot.payouts"))
    try:
        return redirect(payout_service.stripe_onboarding_url(current_user), code=303)
    except stripe.StripeError:
        current_app.logger.exception("Stripe-Onboarding für Nutzer %s fehlgeschlagen", current_user.id)
        flash("Stripe ist gerade nicht erreichbar. Bitte versuche es später erneut.", "danger")
        return redirect(url_for("pilot.payouts"))


@bp.route("/auszahlungen/stripe-dashboard", methods=["POST"])
@pilot_required
def stripe_dashboard():
    if not current_user.stripe_account_id or "stripe" not in payout_service.available_methods():
        abort(404)
    try:
        return redirect(payout_service.stripe_dashboard_url(current_user), code=303)
    except stripe.StripeError:
        flash("Das Stripe-Dashboard ist erst nach abgeschlossener Einrichtung verfügbar.", "warning")
        return redirect(url_for("pilot.payouts"))


def _retry_waiting(user):
    for p in Payout.query.filter_by(pilot_id=user.id, status="waiting_details").all():
        payout_service.execute(p)
