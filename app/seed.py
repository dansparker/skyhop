"""Demo data for local development. All demo accounts use the password 'skyhop123'."""
from datetime import date, datetime, timedelta

from .extensions import db
from .models import (Aircraft, Airport, Booking, Conversation, Flight, FlightWish, Message, Payout, Review,
                     User)

DEMO_PASSWORD = "skyhop123"


def _ap(icao):
    return Airport.query.filter_by(icao=icao).one()


def _user(email, first, last, city, bio=None, **kw):
    u = User.query.filter_by(email=email).first()
    if u:
        return u
    u = User(email=email, first_name=first, last_name=last, city=city, bio=bio, email_confirmed=True, **kw)
    u.set_password(DEMO_PASSWORD)
    db.session.add(u)
    db.session.flush()
    return u


def seed_demo():
    if User.query.filter_by(email="anna@skyhop.test").first():
        return

    _user("admin@skyhop.test", "Sky", "Admin", "Wien", is_admin=True)
    anna = _user("anna@skyhop.test", "Anna", "Berger", "Wien",
                 "Fliege seit 12 Jahren, am liebsten über die Wachau und an den Neusiedler See. "
                 "Ich teile meine Leidenschaft gern mit neugierigen Mitflieger:innen!",
                 pilot_status="verified", license_type="PPL", license_number="AT.FCL.4711",
                 flight_hours=820, home_airport_id=_ap("LOAV").id)
    markus = _user("markus@skyhop.test", "Markus", "Huber", "München",
                   "Ex-Segelflieger, jetzt mit der Cirrus unterwegs. Alpenflüge sind meine Spezialität.",
                   pilot_status="verified", license_type="CPL", license_number="DE.FCL.1203",
                   flight_hours=1650, home_airport_id=_ap("EDMO").id)
    lena = _user("lena@skyhop.test", "Lena", "Moser", "Salzburg",
                 "Fluglehrerin am Salzburger Flughafen. Rundflüge über das Salzkammergut – jederzeit!",
                 pilot_status="verified", license_type="CPL", license_number="AT.FCL.9921",
                 flight_hours=2300, home_airport_id=_ap("LOWS").id)
    thomas = _user("thomas@skyhop.test", "Thomas", "Keller", "Zürich",
                   "Wochenendpilot mit Faible für Inseln und Küsten.",
                   pilot_status="verified", license_type="PPL", license_number="CH.FCL.5532",
                   flight_hours=410, home_airport_id=_ap("LSZH").id)
    julia = _user("julia@skyhop.test", "Julia", "Steiner", "Wien",
                  "Fotografin, liebe Luftaufnahmen und neue Perspektiven.")
    peter = _user("peter@skyhop.test", "Peter", "Wagner", "Graz", "Fliege zum ersten Mal in einer Kleinmaschine!")
    _user("max@skyhop.test", "Max", "Gruber", "Linz", pilot_status="pending", license_type="LAPL",
          license_number="AT.FCL.0815", flight_hours=95, home_airport_id=_ap("LOWL").id)

    c172 = Aircraft(owner_id=anna.id, registration="OE-KAB", manufacturer="Cessna", model="172 Skyhawk",
                    seats=3, cruise_speed_kt=115, year=2008, description="Hochdecker – perfekte Sicht nach unten.")
    sr22 = Aircraft(owner_id=markus.id, registration="D-ECMH", manufacturer="Cirrus", model="SR22",
                    seats=3, cruise_speed_kt=170, year=2016, description="Mit Rettungsfallschirm (CAPS) und Klimaanlage.")
    da40 = Aircraft(owner_id=lena.id, registration="OE-DLM", manufacturer="Diamond", model="DA40 NG",
                    seats=3, cruise_speed_kt=130, year=2019, description="Österreichisches Flugzeug mit großer Glaskuppel.")
    pa28 = Aircraft(owner_id=thomas.id, registration="HB-PTK", manufacturer="Piper", model="PA-28 Archer",
                    seats=3, cruise_speed_kt=120, year=2001)
    db.session.add_all([c172, sr22, da40, pa28])
    db.session.flush()

    today = datetime.now().replace(minute=0, second=0, microsecond=0)

    def day(n, hour):
        return (today + timedelta(days=n)).replace(hour=hour)

    def flight(pilot, ac, dep, arr, ftype, title, when, minutes, seats, cost, desc, ret=None, status="published"):
        f = Flight(pilot_id=pilot.id, aircraft_id=ac.id, departure_id=_ap(dep).id, arrival_id=_ap(arr).id,
                   flight_type=ftype, title=title, departure_time=when, return_time=ret,
                   duration_minutes=minutes, seats_total=seats, direct_cost=cost,
                   price_per_seat=Flight.calc_price(cost, seats), description=desc, status=status,
                   meeting_point="Vor dem Clubhaus, 30 Minuten vor Abflug")
        db.session.add(f)
        return f

    flights = [
        flight(anna, c172, "LOAV", "LOAV", "roundtrip", "Wachau-Rundflug zur Marillenblüte", day(3, 10), 75, 3, 320,
               "Wir fliegen entlang der Donau über Melk, Dürnstein und Krems und zurück über den Wienerwald."),
        flight(anna, c172, "LOAV", "LJPZ", "daytrip", "Tagesausflug ans Meer: Portorož", day(9, 8), 120, 3, 760,
               "Kaffee am Meer! Mittagessen in Piran, Rückflug am späten Nachmittag.", ret=day(9, 17)),
        flight(anna, c172, "LOAV", "LHSM", "trip", "Plattensee-Wochenende", day(16, 9), 70, 2, 390,
               "One-way an den Balaton – ideal für ein verlängertes Wochenende."),
        flight(markus, sr22, "EDMO", "LIPZ", "trip", "Über die Alpen nach Venedig", day(5, 9), 95, 3, 980,
               "Spektakuläre Alpenüberquerung über den Brenner, Landung in Venedig."),
        flight(markus, sr22, "EDMO", "EDMO", "roundtrip", "Königsschlösser & Zugspitze", day(2, 14), 60, 3, 520,
               "Neuschwanstein, Linderhof und ein Blick auf die Zugspitze aus der Luft."),
        flight(markus, sr22, "EDMO", "EDXW", "trip", "Von München nach Sylt", day(20, 8), 210, 2, 1350,
               "Mit kurzem Tankstopp – Nordseeluft zum Frühstück."),
        flight(lena, da40, "LOWS", "LOWS", "roundtrip", "Salzkammergut-Seenflug", day(1, 11), 45, 3, 280,
               "Wolfgangsee, Mondsee, Attersee und der Dachstein-Gletscher."),
        flight(lena, da40, "LOWS", "LOWZ", "daytrip", "Gletscherblick in Zell am See", day(7, 9), 40, 3, 340,
               "Rauf zum Kitzsteinhorn, Mittagessen am See, retour über den Großglockner.", ret=day(7, 16)),
        flight(lena, da40, "LOWS", "LIPB", "trip", "Salzburg → Bozen über die Dolomiten", day(12, 10), 70, 3, 560,
               "Großglockner und Dolomiten in einem Flug – ein Traum für Fotograf:innen."),
        flight(thomas, pa28, "LSZH", "LSZS", "daytrip", "Engadin & St. Moritz", day(4, 9), 55, 3, 480,
               "Tagesausflug ins Engadin. Wanderung am Silsersee möglich.", ret=day(4, 17)),
        flight(thomas, pa28, "LSZH", "LFMN", "trip", "Ab an die Côte d'Azur", day(14, 8), 180, 2, 1180,
               "Über Genfer See und Mont Blanc bis nach Nizza."),
        flight(thomas, pa28, "LSZH", "LSZH", "roundtrip", "Rheinfall & Bodensee", day(6, 15), 50, 3, 300,
               "Sonnenuntergangsflug über den Rheinfall und den Bodensee."),
    ]
    # Past flights with reviews
    past1 = flight(anna, c172, "LOAV", "LOAV", "roundtrip", "Neusiedler See bei Sonnenuntergang", day(-14, 18), 60, 3,
                   300, "Abendflug über den Neusiedler See.", status="completed")
    past2 = flight(lena, da40, "LOWS", "LOWS", "roundtrip", "Dachstein-Rundflug", day(-21, 10), 50, 3, 290,
                   "Rundflug zum Dachstein.", status="completed")
    db.session.flush()

    for f, passenger, text, rating in [
        (past1, julia, "Unglaublich schöne Fotos gemacht! Anna erklärt alles ruhig und sympathisch.", 5),
        (past1, peter, "Mein erster Flug in einer Cessna – Gänsehaut. Danke, Anna!", 5),
        (past2, julia, "Super organisiert, tolles Wetter, Lena ist eine sehr erfahrene Pilotin.", 5),
        (past2, peter, "Sehr schön, nur etwas windig. Gerne wieder!", 4),
    ]:
        b = Booking(flight_id=f.id, passenger_id=passenger.id, seats=1, status="completed",
                    total_price=f.price_per_seat, service_fee=round(f.price_per_seat * 0.1),
                    paid_at=f.departure_time - timedelta(days=3))
        db.session.add(b)
        db.session.flush()
        db.session.add(Review(booking_id=b.id, author_id=passenger.id, target_id=f.pilot_id, rating=rating,
                              comment=text, created_at=f.departure_time + timedelta(days=1)))
        db.session.add(Review(booking_id=b.id, author_id=f.pilot_id, target_id=passenger.id, rating=5,
                              comment="Pünktlich und gut gelaunt – jederzeit wieder!",
                              created_at=f.departure_time + timedelta(days=1)))

    # Payouts for the past flights: one already paid out, one still in the holding period
    db.session.flush()
    db.session.add(Payout(pilot_id=anna.id, flight_id=past1.id, amount=sum(b.pilot_payout for b in past1.bookings),
                          status="paid", method="demo", due_at=past1.departure_time + timedelta(days=2),
                          paid_at=past1.departure_time + timedelta(days=2)))
    db.session.add(Payout(pilot_id=lena.id, flight_id=past2.id, amount=sum(b.pilot_payout for b in past2.bookings),
                          status="waiting_details", due_at=past2.departure_time + timedelta(days=2)))

    # Open bookings on upcoming flights
    wachau = flights[0]
    db.session.add(Booking(flight_id=wachau.id, passenger_id=julia.id, seats=1, status="paid",
                           total_price=wachau.price_per_seat, service_fee=round(wachau.price_per_seat * 0.1),
                           paid_at=datetime.utcnow(), message="Ich bringe meine Kamera mit 📷"))
    db.session.add(Booking(flight_id=flights[3].id, passenger_id=peter.id, seats=2, status="pending",
                           total_price=2 * flights[3].price_per_seat,
                           service_fee=round(2 * flights[3].price_per_seat * 0.1),
                           message="Hallo Markus, meine Frau und ich würden gern mitfliegen!"))

    conv = Conversation(user1_id=julia.id, user2_id=anna.id, flight_id=wachau.id)
    db.session.add(conv)
    db.session.flush()
    db.session.add_all([
        Message(conversation_id=conv.id, sender_id=julia.id, body="Hallo Anna! Darf ich durchs offene Fenster fotografieren?",
                created_at=datetime.utcnow() - timedelta(hours=5)),
        Message(conversation_id=conv.id, sender_id=anna.id,
                body="Hi Julia! Ja, die Cessna hat ein Fenster, das man im Flug öffnen kann. Perfekt für Fotos 😊",
                created_at=datetime.utcnow() - timedelta(hours=4), read_at=datetime.utcnow()),
    ])

    db.session.add_all([
        FlightWish(user_id=peter.id, departure_id=_ap("LOWG").id, arrival_id=_ap("LDLO").id,
                   date_from=date.today() + timedelta(days=10), date_to=date.today() + timedelta(days=30),
                   seats=2, budget_per_seat=250, message="Gerne ein Wochenende auf Lošinj!"),
        FlightWish(user_id=julia.id, departure_id=_ap("LOWW").id, arrival_id=None,
                   date_from=date.today() + timedelta(days=2), date_to=date.today() + timedelta(days=21),
                   seats=1, budget_per_seat=150, message="Rundflug für Luftaufnahmen der Wiener Innenstadt."),
    ])
    db.session.commit()
