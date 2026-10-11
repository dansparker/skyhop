import csv
import io
from datetime import datetime

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for

from .. import payouts as payout_service
from ..extensions import db
from ..models import Booking, Flight, NewsletterSubscriber, Payout, Review, User
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
        "subscribers": NewsletterSubscriber.query.filter_by(status="confirmed").count(),
        "open_refunds": sum(1 for b in Booking.query.filter_by(status="cancelled")
                            if b.paid_at and b.refund_status != "refunded"),
        "open_payouts": Payout.query.filter(Payout.status != "paid").count(),
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


@bp.route("/newsletter")
@admin_required
def newsletter():
    subs = NewsletterSubscriber.query.order_by(NewsletterSubscriber.requested_at.desc()).all()
    counts = {k: sum(1 for s in subs if s.status == k) for k in NewsletterSubscriber.STATUS}
    return render_template("admin/newsletter.html", subs=subs, counts=counts)


@bp.route("/newsletter.csv")
@admin_required
def newsletter_csv():
    """Export of confirmed subscribers incl. double opt-in proof (timestamps + IPs)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["email", "angefragt_am", "anfrage_ip", "bestaetigt_am", "bestaetigungs_ip"])
    for s in NewsletterSubscriber.query.filter_by(status="confirmed").order_by(NewsletterSubscriber.email):
        w.writerow([s.email, s.requested_at.isoformat() if s.requested_at else "", s.request_ip or "",
                    s.confirmed_at.isoformat() if s.confirmed_at else "", s.confirm_ip or ""])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=skyhop-newsletter.csv"})


@bp.route("/zahlungen")
@admin_required
def payments_overview():
    paid = Booking.query.filter(Booking.paid_at.isnot(None)).order_by(Booking.paid_at.desc()).all()
    open_refunds = [b for b in paid if b.status == "cancelled" and b.refund_status in (None, "failed", "manual")]
    return render_template("admin/payments.html", paid=paid, open_refunds=open_refunds)


@bp.route("/zahlungen/<int:booking_id>/erstattet", methods=["POST"])
@admin_required
def mark_refunded(booking_id):
    booking = db.session.get(Booking, booking_id) or abort(404)
    booking.refund_status = "refunded"
    booking.refunded_at = datetime.utcnow()
    db.session.commit()
    flash(f"Buchung #{booking.id} als erstattet markiert.", "success")
    return redirect(url_for("admin.payments_overview"))


@bp.route("/auszahlungen")
@admin_required
def payouts():
    items = Payout.query.order_by(Payout.created_at.desc()).all()
    sums = {k: sum(p.amount for p in items if p.status == k) for k in Payout.STATUS}
    return render_template("admin/payouts.html", payouts=items, sums=sums,
                           methods=payout_service.available_methods())


@bp.route("/auszahlungen/<int:payout_id>/<action>", methods=["POST"])
@admin_required
def payout_action(payout_id, action):
    payout = db.session.get(Payout, payout_id) or abort(404)
    if action == "ausfuehren":
        payout_service.execute(payout, force=True)
        flash(f"Auszahlung #{payout.id}: {payout.status_label}"
              + (f" – {payout.error}" if payout.error else ""), "success" if payout.status == "paid" else "info")
    elif action == "manuell" and payout.status != "paid":
        payout.method = "manual"
        payout.status = "paid"
        payout.paid_at = datetime.utcnow()
        payout.error = None
        notify(payout.pilot, f"Auszahlung über {payout.amount} € für „{payout.flight.title}“ wurde überwiesen.",
               url_for("pilot.payouts"))
        db.session.commit()
        flash(f"Auszahlung #{payout.id} als manuell überwiesen markiert.", "success")
    else:
        abort(400)
    return redirect(url_for("admin.payouts"))


@bp.route("/auszahlungen/lauf", methods=["POST"])
@admin_required
def payouts_run():
    result = payout_service.run_due()
    flash(f"{result['completed_flights']} Flüge automatisch abgeschlossen, "
          f"{result['processed']} fällige Auszahlungen bearbeitet.", "info")
    return redirect(url_for("admin.payouts"))
