import math
from datetime import datetime, timedelta

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db

AVATAR_COLORS = ["#2563eb", "#0891b2", "#7c3aed", "#db2777", "#ea580c", "#16a34a", "#ca8a04", "#4f46e5"]


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    city = db.Column(db.String(120))
    bio = db.Column(db.Text)
    phone = db.Column(db.String(40))
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # E-mail double opt-in & preferences
    email_confirmed = db.Column(db.Boolean, default=False, nullable=False)
    email_confirmed_at = db.Column(db.DateTime)
    email_notifications = db.Column(db.Boolean, default=True, nullable=False)

    # Pilot data
    pilot_status = db.Column(db.String(20), default="none")  # none, pending, verified, rejected
    license_type = db.Column(db.String(20))
    license_number = db.Column(db.String(60))
    flight_hours = db.Column(db.Integer)
    home_airport_id = db.Column(db.Integer, db.ForeignKey("airport.id"))
    home_airport = db.relationship("Airport")

    aircraft = db.relationship("Aircraft", backref="owner", lazy=True, cascade="all, delete-orphan")
    flights = db.relationship("Flight", backref="pilot", lazy=True, foreign_keys="Flight.pilot_id")
    bookings = db.relationship("Booking", backref="passenger", lazy=True, foreign_keys="Booking.passenger_id")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def short_name(self):
        return f"{self.first_name} {self.last_name[:1]}."

    @property
    def initials(self):
        return (self.first_name[:1] + self.last_name[:1]).upper()

    @property
    def avatar_color(self):
        return AVATAR_COLORS[(self.id or 0) % len(AVATAR_COLORS)]

    @property
    def is_pilot(self):
        return self.pilot_status == "verified"

    @property
    def reviews_received(self):
        return Review.query.filter_by(target_id=self.id).order_by(Review.created_at.desc()).all()

    @property
    def rating(self):
        reviews = Review.query.filter_by(target_id=self.id).all()
        if not reviews:
            return None
        return round(sum(r.rating for r in reviews) / len(reviews), 1)

    @property
    def rating_count(self):
        return Review.query.filter_by(target_id=self.id).count()

    @property
    def completed_flights_count(self):
        return Flight.query.filter_by(pilot_id=self.id, status="completed").count()


class Airport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    icao = db.Column(db.String(4), unique=True, nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    city = db.Column(db.String(120), nullable=False)
    country = db.Column(db.String(2), nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lon = db.Column(db.Float, nullable=False)

    @property
    def label(self):
        return f"{self.icao} – {self.city} ({self.name})"

    def distance_to(self, other):
        return haversine_km(self.lat, self.lon, other.lat, other.lon)


class Aircraft(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    registration = db.Column(db.String(12), nullable=False)
    manufacturer = db.Column(db.String(80), nullable=False)
    model = db.Column(db.String(80), nullable=False)
    seats = db.Column(db.Integer, nullable=False)  # passenger seats (without pilot)
    cruise_speed_kt = db.Column(db.Integer, default=110)
    year = db.Column(db.Integer)
    description = db.Column(db.Text)

    @property
    def label(self):
        return f"{self.manufacturer} {self.model} ({self.registration})"


ACTIVE_BOOKING_STATES = ("accepted", "paid", "completed")


class Flight(db.Model):
    TYPES = {
        "trip": "Streckenflug",
        "roundtrip": "Rundflug",
        "daytrip": "Tagesausflug",
    }
    STATUS = {
        "published": "Veröffentlicht",
        "cancelled": "Abgesagt",
        "completed": "Durchgeführt",
    }

    id = db.Column(db.Integer, primary_key=True)
    pilot_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    aircraft_id = db.Column(db.Integer, db.ForeignKey("aircraft.id"), nullable=False)
    departure_id = db.Column(db.Integer, db.ForeignKey("airport.id"), nullable=False)
    arrival_id = db.Column(db.Integer, db.ForeignKey("airport.id"), nullable=False)
    flight_type = db.Column(db.String(20), nullable=False, default="trip")
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text)
    meeting_point = db.Column(db.String(200))
    departure_time = db.Column(db.DateTime, nullable=False, index=True)
    return_time = db.Column(db.DateTime)
    duration_minutes = db.Column(db.Integer, nullable=False)
    seats_total = db.Column(db.Integer, nullable=False)
    direct_cost = db.Column(db.Integer, nullable=False)  # EUR, total direct costs of the flight
    price_per_seat = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default="published", index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    aircraft = db.relationship("Aircraft")
    departure = db.relationship("Airport", foreign_keys=[departure_id])
    arrival = db.relationship("Airport", foreign_keys=[arrival_id])
    bookings = db.relationship("Booking", backref="flight", lazy=True, cascade="all, delete-orphan")

    @staticmethod
    def calc_price(direct_cost, seats):
        """EU cost-sharing rule: the pilot pays at least an equal share of direct costs."""
        if not seats or seats < 1:
            return 0
        return math.ceil(direct_cost / (seats + 1))

    @property
    def type_label(self):
        return self.TYPES.get(self.flight_type, self.flight_type)

    @property
    def status_label(self):
        return self.STATUS.get(self.status, self.status)

    @property
    def seats_booked(self):
        return sum(b.seats for b in self.bookings if b.status in ACTIVE_BOOKING_STATES)

    @property
    def seats_available(self):
        return max(self.seats_total - self.seats_booked, 0)

    @property
    def pending_requests(self):
        return [b for b in self.bookings if b.status == "pending"]

    @property
    def arrival_time(self):
        return self.departure_time + timedelta(minutes=self.duration_minutes)

    @property
    def is_past(self):
        return self.departure_time < datetime.now()

    @property
    def is_bookable(self):
        return self.status == "published" and not self.is_past and self.seats_available > 0

    @property
    def distance_km(self):
        if self.departure_id == self.arrival_id:
            return None
        return round(self.departure.distance_to(self.arrival))

    @property
    def route_label(self):
        if self.flight_type == "roundtrip" or self.departure_id == self.arrival_id:
            return f"Rundflug ab {self.departure.city}"
        return f"{self.departure.city} → {self.arrival.city}"

    @property
    def duration_label(self):
        h, m = divmod(self.duration_minutes, 60)
        if h and m:
            return f"{h} h {m} min"
        return f"{h} h" if h else f"{m} min"


class Booking(db.Model):
    STATUS = {
        "pending": "Angefragt",
        "accepted": "Bestätigt – Zahlung offen",
        "paid": "Gebucht",
        "declined": "Abgelehnt",
        "cancelled": "Storniert",
        "completed": "Abgeschlossen",
    }

    id = db.Column(db.Integer, primary_key=True)
    flight_id = db.Column(db.Integer, db.ForeignKey("flight.id"), nullable=False)
    passenger_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    seats = db.Column(db.Integer, nullable=False, default=1)
    message = db.Column(db.Text)
    status = db.Column(db.String(20), default="pending", index=True)
    total_price = db.Column(db.Integer, nullable=False)
    service_fee = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    paid_at = db.Column(db.DateTime)

    # Payment provider data
    payment_provider = db.Column(db.String(20))  # "stripe" or "demo"
    stripe_session_id = db.Column(db.String(255), index=True)
    stripe_payment_intent = db.Column(db.String(255))
    paypal_order_id = db.Column(db.String(64), index=True)
    paypal_capture_id = db.Column(db.String(64))
    refund_status = db.Column(db.String(20))  # None, "refunded", "failed", "manual"
    refunded_at = db.Column(db.DateTime)

    @property
    def status_label(self):
        return self.STATUS.get(self.status, self.status)

    @property
    def pilot_payout(self):
        return self.total_price - self.service_fee

    @property
    def is_reviewable(self):
        return self.status in ("paid", "completed") and self.flight.is_past

    def review_by(self, user):
        return Review.query.filter_by(booking_id=self.id, author_id=user.id).first()


class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    target_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    booking = db.relationship("Booking")
    author = db.relationship("User", foreign_keys=[author_id])
    target = db.relationship("User", foreign_keys=[target_id])


class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user1_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user2_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    flight_id = db.Column(db.Integer, db.ForeignKey("flight.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    user1 = db.relationship("User", foreign_keys=[user1_id])
    user2 = db.relationship("User", foreign_keys=[user2_id])
    flight = db.relationship("Flight")
    messages = db.relationship("Message", backref="conversation", lazy=True,
                               order_by="Message.created_at", cascade="all, delete-orphan")

    def other(self, user):
        return self.user2 if self.user1_id == user.id else self.user1

    def has_member(self, user):
        return user.id in (self.user1_id, self.user2_id)

    def unread_for(self, user):
        return sum(1 for m in self.messages if m.sender_id != user.id and m.read_at is None)

    @property
    def last_message(self):
        return self.messages[-1] if self.messages else None


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversation.id"), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read_at = db.Column(db.DateTime)

    sender = db.relationship("User")


class Favorite(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), primary_key=True)
    flight_id = db.Column(db.Integer, db.ForeignKey("flight.id"), primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    flight = db.relationship("Flight")


class FlightWish(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    departure_id = db.Column(db.Integer, db.ForeignKey("airport.id"), nullable=False)
    arrival_id = db.Column(db.Integer, db.ForeignKey("airport.id"))
    date_from = db.Column(db.Date, nullable=False)
    date_to = db.Column(db.Date, nullable=False)
    seats = db.Column(db.Integer, default=1)
    budget_per_seat = db.Column(db.Integer)
    message = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")
    departure = db.relationship("Airport", foreign_keys=[departure_id])
    arrival = db.relationship("Airport", foreign_keys=[arrival_id])


class NewsletterSubscriber(db.Model):
    """Newsletter consent with double opt-in. Request/confirm timestamps and IPs serve as proof of consent."""

    STATUS = {"pending": "Bestätigung ausstehend", "confirmed": "Bestätigt", "unsubscribed": "Abgemeldet"}

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    status = db.Column(db.String(20), default="pending", nullable=False, index=True)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    request_ip = db.Column(db.String(64))
    confirmed_at = db.Column(db.DateTime)
    confirm_ip = db.Column(db.String(64))
    unsubscribed_at = db.Column(db.DateTime)

    @property
    def status_label(self):
        return self.STATUS.get(self.status, self.status)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    text = db.Column(db.String(300), nullable=False)
    link = db.Column(db.String(300))
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
