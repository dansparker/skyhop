from datetime import datetime, timedelta

from app.extensions import db
from app.models import Booking, Flight, Message, Notification, Review, User
from app.seed import seed_demo

from .conftest import login, logout, make_user, upload_pilot_documents


def _create_flight(client, **overrides):
    when = datetime.now() + timedelta(days=5)
    data = {
        "flight_type": "trip", "title": "Wien nach Graz", "departure": "LOWW", "arrival": "LOWG",
        "date": when.strftime("%Y-%m-%d"), "time": "10:00", "duration_minutes": "60",
        "aircraft_id": "1", "seats_total": "3", "direct_cost": "400", "description": "Test",
    }
    data.update(overrides)
    return client.post("/fluege/neu", data=data, follow_redirects=True)


def test_public_pages(client):
    for url in ["/", "/fluege", "/so-funktionierts", "/faq", "/sicherheit", "/impressum", "/flugwuensche/",
                "/anmelden", "/registrieren"]:
        assert client.get(url).status_code == 200, url
    assert client.get("/gibtsnicht").status_code == 404


def test_register_and_login(client):
    r = client.post("/registrieren", data={
        "first_name": "Eva", "last_name": "Muster", "email": "eva@example.com",
        "password": "geheim123", "password2": "geheim123", "terms": "on",
    }, follow_redirects=True)
    assert "Willkommen an Bord, Eva" in r.get_data(as_text=True)
    logout(client)
    r = client.post("/anmelden", data={"email": "eva@example.com", "password": "falsch"}, follow_redirects=True)
    assert "falsch" in r.get_data(as_text=True)
    r = login(client, "eva@example.com")
    assert r.status_code == 200
    # Duplicate
    logout(client)
    r = client.post("/registrieren", data={
        "first_name": "Eva", "last_name": "M", "email": "eva@example.com",
        "password": "geheim123", "password2": "geheim123", "terms": "on",
    }, follow_redirects=True)
    assert "existiert bereits" in r.get_data(as_text=True)


def test_price_calculation():
    assert Flight.calc_price(400, 3) == 100
    assert Flight.calc_price(401, 3) == 101
    assert Flight.calc_price(300, 1) == 150


def test_pilot_verification_flow(client, app):
    make_user("admin@x.at", admin=True)
    make_user("max@x.at")
    login(client, "max@x.at")
    # Not yet a pilot → redirected
    r = client.get("/fluege/neu")
    assert r.status_code == 302
    form = {"license_type": "PPL", "license_number": "AT.999", "flight_hours": "120", "home_airport": "LOWL",
            "medical": "on"}
    # Without uploaded proofs the application is refused
    client.post("/pilot/werden", data=form)
    max_ = User.query.filter_by(email="max@x.at").one()
    assert max_.pilot_status == "none"
    upload_pilot_documents(client)
    client.post("/pilot/werden", data=form)
    db.session.refresh(max_)
    assert max_.pilot_status == "pending"
    logout(client)
    login(client, "admin@x.at")
    client.post(f"/admin/piloten/{max_.id}/approve")
    db.session.refresh(max_)
    assert max_.pilot_status == "verified"


def test_full_booking_flow(client, app):
    pilot = make_user("anna@x.at", pilot=True)
    passenger = make_user("julia@x.at")
    login(client, "anna@x.at")
    r = _create_flight(client)
    assert "Dein Flug ist jetzt online" in r.get_data(as_text=True)
    flight = Flight.query.one()
    assert flight.price_per_seat == 100
    logout(client)

    # Search finds it (also by radius from Vöslau)
    assert "Wien nach Graz" in client.get("/fluege?from=Wien").get_data(as_text=True)
    assert "Wien nach Graz" in client.get("/fluege?from=LOAV&radius=50").get_data(as_text=True)
    assert "Wien nach Graz" not in client.get("/fluege?from=Salzburg").get_data(as_text=True)
    assert "Wien nach Graz" not in client.get("/fluege?seats=4").get_data(as_text=True)

    login(client, "julia@x.at")
    client.post(f"/fluege/{flight.id}/buchen", data={"seats": "2", "message": "Hallo!"})
    booking = Booking.query.one()
    assert booking.status == "pending" and booking.total_price == 200 and booking.service_fee == 20
    assert Message.query.count() == 1
    assert Notification.query.filter_by(user_id=pilot.id).count() == 1
    # Passenger cannot accept own request
    assert client.post(f"/buchungen/{booking.id}/annehmen").status_code == 403
    logout(client)

    login(client, "anna@x.at")
    client.post(f"/buchungen/{booking.id}/annehmen")
    db.session.refresh(booking)
    assert booking.status == "accepted"
    assert flight.seats_available == 1
    logout(client)

    login(client, "julia@x.at")
    client.post(f"/buchungen/{booking.id}/bezahlen", data={"confirm": "on"})
    db.session.refresh(booking)
    assert booking.status == "paid"
    # Review not yet possible
    client.post(f"/buchungen/{booking.id}/bewerten", data={"rating": "5"})
    assert Review.query.count() == 0

    # Flight happens
    flight.departure_time = datetime.now() - timedelta(hours=3)
    db.session.commit()
    client.post(f"/buchungen/{booking.id}/bewerten", data={"rating": "5", "comment": "Toll!"})
    assert Review.query.count() == 1
    assert pilot.rating == 5.0
    logout(client)

    login(client, "anna@x.at")
    client.post(f"/fluege/{flight.id}/abschliessen")
    db.session.refresh(booking)
    assert flight.status == "completed" and booking.status == "completed"
    assert passenger.id  # silence unused


def test_cannot_overbook_or_book_own_flight(client):
    make_user("anna@x.at", pilot=True)
    make_user("a@x.at")
    login(client, "anna@x.at")
    _create_flight(client, seats_total="1")
    flight = Flight.query.one()
    client.post(f"/fluege/{flight.id}/buchen", data={"seats": "1"})
    assert Booking.query.count() == 0
    logout(client)
    login(client, "a@x.at")
    client.post(f"/fluege/{flight.id}/buchen", data={"seats": "2"})
    assert Booking.query.count() == 0


def test_flight_validation(client):
    make_user("anna@x.at", pilot=True)
    login(client, "anna@x.at")
    r = _create_flight(client, seats_total="5")
    assert "nur 3 Passagierplätze" in r.get_data(as_text=True)
    r = _create_flight(client, date="2000-01-01")
    assert "in der Zukunft" in r.get_data(as_text=True)
    r = _create_flight(client, arrival="LOWW")
    assert "identisch" in r.get_data(as_text=True)
    r = _create_flight(client, flight_type="roundtrip", arrival="")
    assert "online" in r.get_data(as_text=True)
    assert Flight.query.one().departure_id == Flight.query.one().arrival_id


def test_cancel_flight_notifies_passengers(client):
    make_user("anna@x.at", pilot=True)
    p = make_user("p@x.at")
    login(client, "anna@x.at")
    _create_flight(client)
    flight = Flight.query.one()
    logout(client)
    login(client, "p@x.at")
    client.post(f"/fluege/{flight.id}/buchen", data={"seats": "1"})
    logout(client)
    login(client, "anna@x.at")
    client.post(f"/fluege/{flight.id}/absagen", data={"reason": "Wetter"})
    assert flight.status == "cancelled"
    assert Booking.query.one().status == "cancelled"
    assert Notification.query.filter_by(user_id=p.id).count() >= 1


def test_messaging_privacy(client):
    a = make_user("a@x.at")
    b = make_user("b@x.at")
    make_user("c@x.at")
    login(client, "a@x.at")
    r = client.get(f"/nachrichten/neu/{b.id}")
    conv_url = r.headers["Location"]
    client.post(conv_url, data={"body": "Hi B"})
    logout(client)
    login(client, "c@x.at")
    assert client.get(conv_url).status_code == 403
    logout(client)
    login(client, "b@x.at")
    assert "Hi B" in client.get(conv_url).get_data(as_text=True)
    assert a.id


def test_wish_and_matching_notification(client):
    make_user("anna@x.at", pilot=True)
    w = make_user("w@x.at")
    login(client, "w@x.at")
    today = datetime.now().date()
    client.post("/flugwuensche/neu", data={"departure": "LOWW", "arrival": "", "seats": "1",
                                           "date_from": today.isoformat(),
                                           "date_to": (today + timedelta(days=10)).isoformat()})
    logout(client)
    login(client, "anna@x.at")
    _create_flight(client)
    texts = [n.text for n in Notification.query.filter_by(user_id=w.id)]
    assert any("Flugwunsch" in t for t in texts)


def test_admin_protected(client):
    make_user("u@x.at")
    login(client, "u@x.at")
    assert client.get("/admin/").status_code == 403


def test_csrf_enforced():
    from app import create_app

    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        r = app.test_client().post("/anmelden", data={"email": "x", "password": "y"})
        assert r.status_code == 400


def test_seed_demo(app, client):
    seed_demo()
    assert User.query.count() >= 7
    assert Flight.query.count() >= 10
    assert Review.query.count() >= 4
    r = client.get("/")
    assert "Wachau" in r.get_data(as_text=True)
    flight = Flight.query.first()
    assert client.get(f"/fluege/{flight.id}").status_code == 200
