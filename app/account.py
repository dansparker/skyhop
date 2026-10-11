"""GDPR helpers: data export (Art. 15/20) and account deletion (Art. 17).

Deletion anonymises the account instead of removing the row: bookings, payments and payouts must be kept for
the statutory retention period (e.g. 7 years under § 132 BAO), and other users keep their message history
and reviews. Everything that identifies the person is removed.
"""
import secrets
from datetime import datetime

from flask import url_for

from . import payments, uploads
from .extensions import db
from .models import (Booking, Conversation, Favorite, Flight, FlightWish, NewsletterSubscriber, Notification,
                     Payout, Review)


def _dt(value):
    return value.isoformat() if value else None


def export_data(user):
    """Everything Skyhop stores about a user, as a JSON-serialisable dict."""
    convs = Conversation.query.filter(db.or_(Conversation.user1_id == user.id, Conversation.user2_id == user.id))
    sub = NewsletterSubscriber.query.filter_by(email=user.email).first()
    return {
        "export_created_at": _dt(datetime.utcnow()),
        "profile": {
            "email": user.email, "first_name": user.first_name, "last_name": user.last_name, "city": user.city,
            "phone": user.phone, "bio": user.bio, "created_at": _dt(user.created_at),
            "email_confirmed_at": _dt(user.email_confirmed_at), "email_notifications": user.email_notifications,
            "terms_accepted_at": _dt(user.terms_accepted_at), "terms_version": user.terms_version,
            "has_profile_photo": bool(user.avatar_filename),
        },
        "pilot": {
            "status": user.pilot_status, "license_type": user.license_type, "license_number": user.license_number,
            "flight_hours": user.flight_hours, "home_airport": user.home_airport.icao if user.home_airport else None,
            "documents": [{"kind": d.kind, "original_name": d.original_name, "status": d.status,
                           "uploaded_at": _dt(d.uploaded_at)} for d in user.documents],
            "aircraft": [{"registration": a.registration, "manufacturer": a.manufacturer, "model": a.model,
                          "seats": a.seats} for a in user.aircraft],
            "payout_method": user.payout_method, "paypal_payout_email": user.paypal_payout_email,
        },
        "flights_offered": [{"id": f.id, "title": f.title, "departure_time": _dt(f.departure_time),
                             "route": f.route_label, "status": f.status, "price_per_seat": f.price_per_seat}
                            for f in user.flights],
        "bookings": [{"id": b.id, "flight": b.flight.title, "departure_time": _dt(b.flight.departure_time),
                      "seats": b.seats, "total_price_eur": b.total_price, "status": b.status,
                      "payment_provider": b.payment_provider, "paid_at": _dt(b.paid_at),
                      "refund_status": b.refund_status} for b in user.bookings],
        "payouts": [{"flight": p.flight.title, "amount_eur": p.amount, "status": p.status, "paid_at": _dt(p.paid_at)}
                    for p in Payout.query.filter_by(pilot_id=user.id)],
        "reviews_written": [{"about": r.target.short_name, "rating": r.rating, "comment": r.comment,
                             "created_at": _dt(r.created_at)} for r in Review.query.filter_by(author_id=user.id)],
        "reviews_received": [{"from": r.author.short_name, "rating": r.rating, "comment": r.comment,
                              "created_at": _dt(r.created_at)} for r in Review.query.filter_by(target_id=user.id)],
        "messages_sent": [{"to": c.other(user).short_name, "body": m.body, "created_at": _dt(m.created_at)}
                          for c in convs for m in c.messages if m.sender_id == user.id],
        "flight_wishes": [{"from": w.departure.icao, "to": w.arrival.icao if w.arrival else None,
                           "date_from": w.date_from.isoformat(), "date_to": w.date_to.isoformat(),
                           "message": w.message} for w in FlightWish.query.filter_by(user_id=user.id)],
        "favorites": [f.flight.title for f in Favorite.query.filter_by(user_id=user.id)],
        "newsletter": {"status": sub.status, "requested_at": _dt(sub.requested_at),
                       "confirmed_at": _dt(sub.confirmed_at)} if sub else None,
    }


def delete_account(user):
    """Cancel open activity, remove personal data and anonymise the account. Commits."""
    from .utils import notify

    now = datetime.now()
    # Upcoming flights offered by the user are cancelled (passengers refunded and informed)
    for f in Flight.query.filter(Flight.pilot_id == user.id, Flight.status == "published").all():
        if f.departure_time > now:
            f.status = "cancelled"
            for b in f.bookings:
                if b.status in ("pending", "accepted", "paid"):
                    if b.status == "paid":
                        payments.refund(b)
                    b.status = "cancelled"
                    notify(b.passenger, f"Der Flug „{f.title}“ wurde abgesagt, weil das Pilotenkonto gelöscht wurde."
                           + (" Du erhältst dein Geld vollständig zurück." if b.paid_at else ""),
                           url_for("bookings.detail", booking_id=b.id))
    # Own open bookings are cancelled (paid ones refunded)
    for b in Booking.query.filter(Booking.passenger_id == user.id,
                                  Booking.status.in_(("pending", "accepted", "paid"))).all():
        if b.flight.departure_time > now:
            if b.status == "paid":
                payments.refund(b)
            b.status = "cancelled"

    # Files
    uploads.delete_file("avatars", user.avatar_filename)
    for d in list(user.documents):
        uploads.delete_file(uploads.DOCUMENT_DIR, d.filename)
        db.session.delete(d)
    for a in user.aircraft:
        uploads.delete_file("aircraft", a.photo_filename)
        a.photo_filename = None
        a.description = None

    # Purely personal records
    Favorite.query.filter_by(user_id=user.id).delete()
    FlightWish.query.filter_by(user_id=user.id).delete()
    Notification.query.filter_by(user_id=user.id).delete()
    NewsletterSubscriber.query.filter_by(email=user.email).delete()
    for c in Conversation.query.filter(db.or_(Conversation.user1_id == user.id, Conversation.user2_id == user.id)):
        for m in c.messages:
            if m.sender_id == user.id:
                m.body = "[Nachricht gelöscht]"

    # Anonymise the account itself
    user.email = f"geloescht-{user.id}-{secrets.token_hex(4)}@deleted.invalid"
    user.first_name, user.last_name = "Gelöschtes", "Konto"
    user.city = user.bio = user.phone = None
    user.avatar_filename = None
    user.license_number = user.paypal_payout_email = None
    user.stripe_account_id = None
    user.payout_method = None
    user.pilot_status = "none"
    user.license_type = None
    user.flight_hours = None
    user.email_confirmed = False
    user.email_notifications = False
    user.is_admin = False
    user.set_password(secrets.token_urlsafe(32))
    user.deleted_at = datetime.utcnow()
    db.session.commit()


def cleanup_documents():
    """Data minimisation: delete pilot documents DOCUMENT_RETENTION_DAYS after they were reviewed."""
    from datetime import timedelta

    from flask import current_app

    from .models import PilotDocument

    cutoff = datetime.utcnow() - timedelta(days=current_app.config.get("DOCUMENT_RETENTION_DAYS", 30))
    old = PilotDocument.query.filter(PilotDocument.status != "pending", PilotDocument.reviewed_at < cutoff).all()
    for d in old:
        uploads.delete_file(uploads.DOCUMENT_DIR, d.filename)
        db.session.delete(d)
    db.session.commit()
    return len(old)
