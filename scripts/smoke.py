"""Smoke test against a real database: seed demo data, log in as every demo role and open all pages.

Usage:  DATABASE_URL=mysql://user:pw@127.0.0.1/skyhop python scripts/smoke.py
Exits with status 1 if any page returns a server error.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.models import Booking, Conversation, Flight  # noqa: E402
from app.seed import DEMO_PASSWORD, seed_demo  # noqa: E402

app = create_app({"CSRF_ENABLED": False, "TESTING": True})
print("Datenbank:", app.config["SQLALCHEMY_DATABASE_URI"].split("@")[-1])

with app.app_context(), app.test_request_context():
    seed_demo()
    flights = [f.id for f in Flight.query.all()]
    bookings = [b.id for b in Booking.query.all()]
    convs = [c.id for c in Conversation.query.all()]

PAGES = ["/", "/fluege", "/fluege?from=Wien&radius=100&type=roundtrip", "/dashboard", "/dashboard?tab=pilot",
         "/nachrichten/", "/benachrichtigungen", "/merkliste", "/profil", "/profil/2", "/pilot/werden",
         "/pilot/flugzeuge", "/pilot/auszahlungen", "/fluege/neu", "/flugwuensche/", "/flugwuensche/neu",
         "/admin/", "/admin/piloten", "/admin/nutzer", "/admin/fluege", "/admin/zahlungen", "/admin/auszahlungen",
         "/admin/newsletter", "/admin/newsletter.csv", "/impressum", "/datenschutz", "/agb", "/stornobedingungen",
         "/profil/daten-export", "/profil/loeschen", "/healthz"]
PAGES += [f"/fluege/{i}" for i in flights] + [f"/buchungen/{i}" for i in bookings]
PAGES += [f"/nachrichten/{i}" for i in convs]

failed = []
for email in ("admin@skyhop.test", "anna@skyhop.test", "julia@skyhop.test", "max@skyhop.test", None):
    client = app.test_client()
    if email:
        r = client.post("/anmelden", data={"email": email, "password": DEMO_PASSWORD})
        assert r.status_code == 302, f"Login {email} fehlgeschlagen"
    for url in PAGES:
        status = client.get(url).status_code
        if status >= 500:
            failed.append((email, url, status))
    # A write path: book, accept, pay, message
    if email == "julia@skyhop.test":
        with app.app_context():
            target = Flight.query.filter(Flight.title.like("%Venedig%")).first()
        r = client.post(f"/fluege/{target.id}/buchen", data={"seats": "1", "message": "Smoke-Test"})
        if r.status_code >= 500:
            failed.append((email, "booking", r.status_code))
    print(f"{email or 'anonym'}: ok" if not failed else f"{email}: {failed}")

with app.app_context():
    runner = app.test_cli_runner()
    result = runner.invoke(args=["cron"])
    print(result.output.strip())
    if result.exit_code != 0:
        failed.append(("cron", result.output, result.exit_code))

if failed:
    print("FEHLER:", failed)
    sys.exit(1)
print("Smoke-Test bestanden.")
