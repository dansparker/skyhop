import io
import json
import os
from datetime import datetime, timedelta

from PIL import Image

from app import uploads
from app.account import cleanup_documents
from app.extensions import db
from app.models import (Booking, Favorite, Flight, FlightWish, NewsletterSubscriber, PilotDocument, User)

from .conftest import PDF_BYTES, login, logout, make_user, png_bytes, upload_pilot_documents


def _file(data, name):
    return (io.BytesIO(data), name)


# --- Profile photos ---------------------------------------------------------------------------------

def test_avatar_upload_strips_metadata_and_resizes(client, app):
    user = make_user("a@x.at")
    login(client, "a@x.at")
    r = client.post("/profil/foto", data={"photo": _file(png_bytes((1200, 900), exif_gps=True), "me.jpg")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "Profilfoto gespeichert" in r.get_data(as_text=True)
    db.session.refresh(user)
    assert user.avatar_filename.endswith(".webp")
    path = os.path.join(app.config["UPLOAD_FOLDER"], "avatars", user.avatar_filename)
    with Image.open(path) as img:
        assert img.size == (512, 512)       # square crop, max 512 px
        assert not img.getexif()            # EXIF incl. GPS removed
    # Publicly served with nosniff, shown in the header
    with app.test_request_context():
        avatar_url = user.avatar_url
    resp = client.get(avatar_url)
    assert resp.status_code == 200 and resp.headers["X-Content-Type-Options"] == "nosniff"
    resp.close()
    assert avatar_url in client.get("/").get_data(as_text=True)
    # Replacing deletes the old file
    old = path
    client.post("/profil/foto", data={"photo": _file(png_bytes(), "b.png")}, content_type="multipart/form-data")
    assert not os.path.exists(old)


def test_avatar_rejects_non_images_and_large_files(client, app):
    make_user("a@x.at")
    login(client, "a@x.at")
    r = client.post("/profil/foto", data={"photo": _file(b"<script>alert(1)</script>", "x.png")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "konnte nicht gelesen werden" in r.get_data(as_text=True)
    r = client.post("/profil/foto", data={"photo": _file(PDF_BYTES, "x.pdf")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "konnte nicht gelesen werden" in r.get_data(as_text=True)
    app.config["MAX_UPLOAD_BYTES"] = 100
    r = client.post("/profil/foto", data={"photo": _file(png_bytes((300, 300)), "big.png")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "zu groß" in r.get_data(as_text=True)
    assert User.query.one().avatar_filename is None


def test_media_route_blocks_traversal_and_unknown_kinds(client):
    assert client.get("/media/documents/anything.pdf").status_code == 404
    assert client.get("/media/avatars/..%2f..%2fskyhop.db").status_code == 404


def test_aircraft_photo(client, app):
    pilot = make_user("p@x.at", pilot=True)
    other = make_user("o@x.at", pilot=True)
    login(client, "p@x.at")
    aircraft = pilot.aircraft[0]
    client.post(f"/pilot/flugzeuge/{aircraft.id}/foto", data={"photo": _file(png_bytes((2400, 1600)), "c.png")},
                content_type="multipart/form-data")
    db.session.refresh(aircraft)
    with Image.open(os.path.join(app.config["UPLOAD_FOLDER"], "aircraft", aircraft.photo_filename)) as img:
        assert max(img.size) == 1600
    # Not allowed on someone else's aircraft
    r = client.post(f"/pilot/flugzeuge/{other.aircraft[0].id}/foto", data={"photo": _file(png_bytes(), "c.png")},
                    content_type="multipart/form-data")
    assert r.status_code == 403


# --- Pilot documents ----------------------------------------------------------------------------------

def test_documents_are_private(client, app):
    make_user("admin@x.at", admin=True)
    make_user("max@x.at")
    make_user("eve@x.at")
    login(client, "max@x.at")
    upload_pilot_documents(client)
    docs = PilotDocument.query.order_by(PilotDocument.kind).all()
    assert {d.kind for d in docs} == {"license", "medical"}
    medical = next(d for d in docs if d.kind == "medical")
    assert medical.consent_at is not None
    license_doc = next(d for d in docs if d.kind == "license")
    r = client.get(f"/dokumente/{license_doc.id}")
    assert r.status_code == 200 and r.data.startswith(b"%PDF") and r.headers["Cache-Control"] == "private, no-store"
    r.close()
    assert "sandbox" in r.headers["Content-Security-Policy"]
    logout(client)
    login(client, "eve@x.at")
    assert client.get(f"/dokumente/{license_doc.id}").status_code == 403
    logout(client)
    assert client.get(f"/dokumente/{license_doc.id}").status_code == 302  # login required
    login(client, "admin@x.at")
    assert client.get(f"/dokumente/{license_doc.id}").status_code == 200
    # Documents are stored outside the public media route
    assert client.get(f"/media/documents/{license_doc.filename}").status_code == 404


def test_medical_requires_explicit_consent_and_valid_type(client):
    make_user("max@x.at")
    login(client, "max@x.at")
    r = client.post("/pilot/dokumente", data={"kind": "medical", "document": _file(PDF_BYTES, "m.pdf")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "ausdrückliche Einwilligung" in r.get_data(as_text=True)
    r = client.post("/pilot/dokumente", data={"kind": "license", "document": _file(b"MZ\x90\x00evil", "l.pdf")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "Erlaubt sind PDF, JPG und PNG" in r.get_data(as_text=True)
    assert PilotDocument.query.count() == 0


def test_admin_approval_marks_documents_and_cleanup_deletes_files(client, app):
    make_user("admin@x.at", admin=True)
    max_ = make_user("max@x.at")
    login(client, "max@x.at")
    upload_pilot_documents(client)
    client.post("/pilot/werden", data={"license_type": "PPL", "license_number": "AT.1", "flight_hours": "50",
                                       "medical": "on"})
    logout(client)
    login(client, "admin@x.at")
    assert "Medical" in client.get("/admin/piloten").get_data(as_text=True)
    client.post(f"/admin/piloten/{max_.id}/approve")
    docs = PilotDocument.query.all()
    assert all(d.status == "approved" and d.reviewed_at for d in docs)
    paths = [os.path.join(app.config["UPLOAD_FOLDER"], "documents", d.filename) for d in docs]
    assert all(os.path.exists(p) for p in paths)
    # Retention period not over yet
    assert cleanup_documents() == 0
    for d in docs:
        d.reviewed_at = datetime.utcnow() - timedelta(days=31)
    db.session.commit()
    assert cleanup_documents() == 2
    assert PilotDocument.query.count() == 0 and not any(os.path.exists(p) for p in paths)


# --- Legal pages & consent ---------------------------------------------------------------------------

def test_legal_pages_render_with_placeholders_and_config(client, app):
    for url in ("/impressum", "/datenschutz", "/agb", "/stornobedingungen"):
        r = client.get(url)
        assert r.status_code == 200, url
    assert "[Name / Firma ergänzen]" in client.get("/impressum").get_data(as_text=True)
    app.config.update(LEGAL_NAME="Skyhop GmbH", LEGAL_ADDRESS="Flugfeldstraße 1, 2540 Bad Vöslau")
    html = client.get("/impressum").get_data(as_text=True)
    assert "Skyhop GmbH" in html and "[Name / Firma ergänzen]" not in html
    # Values are escaped
    app.config["LEGAL_NAME"] = "<script>x</script>"
    assert "<script>x</script>" not in client.get("/impressum").get_data(as_text=True)
    footer = client.get("/").get_data(as_text=True)
    assert all(link in footer for link in ("/datenschutz", "/agb", "/stornobedingungen"))


def test_registration_records_terms_consent(client, app):
    client.post("/registrieren", data={"first_name": "Eva", "last_name": "M", "email": "eva@x.at",
                                       "password": "geheim123", "password2": "geheim123", "terms": "on"})
    user = User.query.filter_by(email="eva@x.at").one()
    assert user.terms_accepted_at and user.terms_version == app.config["TERMS_VERSION"]


def test_no_external_fonts():
    base = open(os.path.join(os.path.dirname(__file__), "..", "app", "templates", "base.html"), encoding="utf-8").read()
    assert "fonts.googleapis" not in base


# --- GDPR: export & deletion --------------------------------------------------------------------------

def _flight(pilot, days=3, status="published"):
    from app.models import Airport

    ap = Airport.query.filter_by(icao="LOAV").one()
    f = Flight(pilot_id=pilot.id, aircraft_id=pilot.aircraft[0].id, departure_id=ap.id, arrival_id=ap.id,
               flight_type="roundtrip", title="Runde", departure_time=datetime.now() + timedelta(days=days),
               duration_minutes=60, seats_total=3, direct_cost=400, price_per_seat=100, status=status)
    db.session.add(f)
    db.session.commit()
    return f


def test_data_export_contains_personal_data(client):
    pilot = make_user("p@x.at", pilot=True)
    user = make_user("u@x.at")
    f = _flight(pilot)
    db.session.add(Booking(flight_id=f.id, passenger_id=user.id, seats=1, status="paid", total_price=100,
                           service_fee=10, paid_at=datetime.utcnow(), payment_provider="demo"))
    db.session.commit()
    login(client, "u@x.at")
    r = client.get("/profil/daten-export")
    assert r.headers["Content-Disposition"].startswith("attachment;")
    data = json.loads(r.data)
    assert data["profile"]["email"] == "u@x.at"
    assert data["bookings"][0]["flight"] == "Runde" and data["bookings"][0]["total_price_eur"] == 100


def test_account_deletion_anonymises_and_refunds(client, app):
    pilot = make_user("p@x.at", pilot=True)
    pax = make_user("pax@x.at")
    f = _flight(pilot)
    b = Booking(flight_id=f.id, passenger_id=pax.id, seats=1, status="paid", total_price=100, service_fee=10,
                paid_at=datetime.utcnow(), payment_provider="demo")
    db.session.add(b)
    db.session.add(NewsletterSubscriber(email="p@x.at", status="confirmed"))
    db.session.add(Favorite(user_id=pilot.id, flight_id=f.id))
    db.session.commit()

    login(client, "p@x.at")
    client.post("/profil/foto", data={"photo": _file(png_bytes(), "me.png")}, content_type="multipart/form-data")
    db.session.refresh(pilot)
    avatar_path = os.path.join(app.config["UPLOAD_FOLDER"], "avatars", pilot.avatar_filename)

    # Wrong password / missing confirmation → nothing happens
    client.post("/profil/loeschen", data={"password": "falsch", "confirm": "LÖSCHEN"})
    client.post("/profil/loeschen", data={"password": "password123", "confirm": "ja"})
    db.session.refresh(pilot)
    assert pilot.deleted_at is None

    client.post("/profil/loeschen", data={"password": "password123", "confirm": "LÖSCHEN"})
    db.session.refresh(pilot)
    db.session.refresh(b)
    db.session.refresh(f)
    assert pilot.deleted_at and pilot.email.endswith("@deleted.invalid") and pilot.first_name == "Gelöschtes"
    assert pilot.avatar_filename is None and not os.path.exists(avatar_path)
    assert f.status == "cancelled" and b.status == "cancelled" and b.refund_status == "refunded"
    assert NewsletterSubscriber.query.count() == 0 and Favorite.query.count() == 0
    # Session ended, old credentials no longer work, profile is gone
    assert client.get("/dashboard").status_code == 302
    r = client.post("/anmelden", data={"email": "p@x.at", "password": "password123"}, follow_redirects=True)
    assert "falsch" in r.get_data(as_text=True)
    assert client.get(f"/profil/{pilot.id}").status_code == 404
    assert FlightWish.query.count() == 0
