# ✈️ Skyhop

**Skyhop** ist eine Open-Source-Mitflugbörse für Kleinflugzeuge – inspiriert von Plattformen wie Wingly.
Privatpilot:innen bieten freie Plätze an, Passagiere fliegen mit und teilen die direkten Kosten nach den
EU-Kostenteilungsregeln.

> ⚠️ Demo-Projekt: Es werden keine echten Flüge vermittelt und keine Zahlungen abgewickelt.

## Funktionen

**Passagiere**
- Flugsuche nach Abflugort, Ziel, **Umkreis (km)**, Datum/Zeitraum, Flugart, Personen und Maximalpreis
- Sortierung nach Datum, Preis, freien Plätzen und Bewertung
- Interaktive Routenkarte (Leaflet/OpenStreetMap) in Suche und Flugdetails
- Buchungsanfrage mit Nachricht → Bestätigung durch Pilot:in → (Demo-)Zahlung → Flug → Bewertung
- Stornierung, Merkliste, Teilen-Funktion
- **Flugwünsche**: Wunschroute + Zeitraum aufgeben, automatische Benachrichtigung bei passendem neuen Flug

**Pilot:innen**
- Pilotenverifizierung (Lizenz, Flugstunden, Medical, Heimatflugplatz) mit Admin-Freigabe
- Flugzeugverwaltung (Kennzeichen, Modell, Sitzplätze, Reisegeschwindigkeit)
- Flüge anbieten: **Streckenflug**, **Rundflug** oder **Tagesausflug** (mit Rückflug)
- Automatische Preisberechnung: `Preis pro Platz = direkte Kosten ÷ (Plätze + 1)` – Pilot:in zahlt immer mit
- Anfragen annehmen/ablehnen, Flug bearbeiten, absagen (mit automatischer Erstattung) oder als durchgeführt markieren
- Dashboard mit offenen Anfragen, Kostenbeteiligung und Ø-Bewertung

**Plattform**
- Registrierung/Login, Profile mit öffentlicher Seite, gegenseitige Bewertungen (1–5 Sterne)
- Nachrichten (Chat pro Flug/Person) mit Ungelesen-Zählern und Lesebestätigung
- Benachrichtigungscenter
- Admin-Bereich: Kennzahlen, Pilotenverifizierung, Nutzer- und Flugverwaltung
- ~70 Flugplätze in AT, DE, CH, IT, SI, HR, CZ, SK, HU, FR
- CSRF-Schutz, gehashte Passwörter, Berechtigungsprüfungen, responsives Design

## Tech-Stack

Python 3.11+ · Flask · Flask-SQLAlchemy (SQLite) · Flask-Login · Jinja2 · Vanilla JS · Leaflet

## Schnellstart

```bash
git clone https://github.com/dansparker/skyhop.git
cd skyhop
python -m venv .venv
# Windows: .venv\Scripts\activate   ·   macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
flask --app run seed       # Demo-Daten anlegen
python run.py              # → http://localhost:5000
```

### Demo-Konten (Passwort jeweils `skyhop123`)

| Rolle              | E-Mail                |
|--------------------|-----------------------|
| Admin              | `admin@skyhop.test`   |
| Pilotin (Wien)     | `anna@skyhop.test`    |
| Pilot (München)    | `markus@skyhop.test`  |
| Pilotin (Salzburg) | `lena@skyhop.test`    |
| Pilot (Zürich)     | `thomas@skyhop.test`  |
| Passagierin        | `julia@skyhop.test`   |
| Passagier          | `peter@skyhop.test`   |
| Pilot (in Prüfung) | `max@skyhop.test`     |

### Weitere Befehle

```bash
pytest                     # Tests ausführen
flask --app run reset-db   # Datenbank leeren
```

### Konfiguration (Umgebungsvariablen)

| Variable            | Bedeutung                                   |
|---------------------|---------------------------------------------|
| `SKYHOP_SECRET_KEY` | Secret Key für Sessions (in Produktion setzen!) |
| `DATABASE_URL`      | SQLAlchemy-URL, Standard: `instance/skyhop.db` |
| `PORT`              | Port für `run.py` (Standard 5000)            |
| `FLASK_DEBUG`       | `0` deaktiviert den Debug-Modus              |

## Projektstruktur

```
app/
  __init__.py        App-Factory, CSRF, Template-Filter, CLI
  models.py          User, Airport, Aircraft, Flight, Booking, Review, Conversation, Message, ...
  airports.py        Flugplatz-Stammdaten
  seed.py            Demo-Daten
  routes/            Blueprints: main, auth, flights, bookings, messages, pilot, profile, wishes, admin
  templates/         Jinja-Templates
  static/            CSS, JS, Favicon
tests/               pytest-Suite
```

## Lizenz

MIT
