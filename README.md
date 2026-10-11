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

**Zahlungen (Stripe und/oder PayPal)**
- Bezahlung über **Stripe Checkout** (Karte, **PayPal**, Apple/Google Pay, SEPA, … – Skyhop sieht keine Zahlungsdaten)
- Alternativ bzw. zusätzlich **PayPal direkt** (REST API v2, eigenes PayPal-Händlerkonto)
- Sind beide konfiguriert, wählen Passagiere die Zahlungsart; Auswahl/Reihenfolge per `PAYMENT_PROVIDERS`
- Bestätigung über Rückleitung **und** verifizierte Webhooks (idempotent, auch wenn der Käufer den Browser schließt)
- Automatische **Erstattung** bei Storno durch Passagier oder Absage durch Pilot:in; Zahlungen für bereits
  stornierte Buchungen werden sofort zurücküberwiesen
- Admin-Übersicht über Zahlungen und fehlgeschlagene Erstattungen
- Ohne `STRIPE_SECRET_KEY` läuft ein Demo-Zahlungsmodus

**Auszahlungen an Pilot:innen**
- Pilot:innen wählen ihren Auszahlungsweg: **Bankkonto über Stripe Connect** (Express-Onboarding inkl.
  Identitätsprüfung, eigenes Stripe-Dashboard) oder **PayPal Payouts** (an die PayPal-E-Mail-Adresse)
- Nach dem Flug wird die Kostenbeteiligung (Buchungen abzüglich Servicegebühr) mit **Haltefrist** eingeplant
- Vergessene Flüge werden automatisch abgeschlossen; `flask --app run payouts` (Cron) zahlt fällige Beträge aus
- Fehlende Auszahlungsdaten → Erinnerung, Auszahlung startet automatisch, sobald die Daten hinterlegt sind
- Idempotent (keine Doppelauszahlungen), Fehler mit Wiederholung, Admin-Übersicht inkl. „jetzt auszahlen“ und
  „manuell erledigt“

**E-Mail & Double-Opt-in**
- **Konto-Bestätigung (Double-Opt-in):** nach der Registrierung kommt ein signierter Link (48 h gültig, an die
  Adresse gebunden). Bis zur Bestätigung kann man stöbern, aber nicht buchen, schreiben oder Flüge anbieten.
  Erneut senden mit Rate-Limit.
- **Passwort vergessen:** einmal verwendbarer Link (1 h), keine Preisgabe, ob ein Konto existiert
- **Newsletter mit DSGVO-konformem Double-Opt-in:** Anmeldung im Footer, bei der Registrierung oder im Profil;
  Bestätigung per Button-Klick (schützt vor Link-Scannern), Nachweis mit Zeitstempel + IP von Anfrage und
  Bestätigung, Abmeldelink + `List-Unsubscribe`-Header, CSV-Export im Admin-Bereich
- **Benachrichtigungen per E-Mail** (Anfragen, Bestätigungen, Absagen, neue Nachrichten – bei Chats nur die
  erste ungelesene), im Profil abschaltbar
- HTML- + Text-Mails über SMTP (jeder Anbieter); ohne SMTP landen Mails im **Dev-Postfach** unter `/dev/mails`

**Uploads**
- **Profilfotos** und **Flugzeugfotos** (auf Flugkarten und Flugdetails): werden mit Pillow geprüft, verkleinert,
  als WebP gespeichert und von allen Metadaten befreit (EXIF inkl. GPS-Position)
- **Lizenz- und Medical-Nachweise** (PDF/JPG/PNG) sind Pflicht für die Pilotenverifizierung: Prüfung per
  Magic Bytes, private Ablage außerhalb des Web-Roots, Abruf nur durch Eigentümer:in und Admins (mit
  `no-store` und Sandbox-CSP), ausdrückliche Einwilligung für Gesundheitsdaten (Art. 9 DSGVO),
  automatische Löschung nach der Prüfung (Standard 30 Tage)
- Größenlimit, zufällige Dateinamen, Schutz vor Path Traversal und Decompression Bombs

**Rechtliches & DSGVO**
- Vorlagen für **Impressum** (§ 5 ECG, § 25 MedienG), **Datenschutzerklärung** (Art. 13 DSGVO),
  **AGB** und **Stornobedingungen** nach österreichischem Recht – Betreiberdaten kommen aus der `.env`,
  fehlende Angaben werden gelb markiert
- Zustimmung zu AGB wird mit Zeitpunkt und Version gespeichert; Links in Registrierung und Checkout
- **Datenexport** (Art. 15/20) als JSON und **Kontolöschung** (Art. 17) mit Anonymisierung, Erstattung
  offener Buchungen und Absage eigener Flüge – Buchungsdaten bleiben für die Aufbewahrungspflicht (§ 132 BAO)
- Keine externen Schriften, nur technisch notwendige Cookies → kein Cookie-Banner nötig

> ⚖️ Die Rechtstexte sind sorgfältig erstellte **Vorlagen** und ersetzen keine Rechtsberatung. Vor dem
> Livegang bitte anwaltlich prüfen lassen.

**Plattform**
- Registrierung/Login, Profile mit öffentlicher Seite, gegenseitige Bewertungen (1–5 Sterne)
- Nachrichten (Chat pro Flug/Person) mit Ungelesen-Zählern und Lesebestätigung
- Benachrichtigungscenter
- Admin-Bereich: Kennzahlen, Pilotenverifizierung, Nutzer- und Flugverwaltung
- ~70 Flugplätze in AT, DE, CH, IT, SI, HR, CZ, SK, HU, FR
- CSRF-Schutz, gehashte Passwörter, Berechtigungsprüfungen, responsives Design

## Tech-Stack

Python 3.11+ · Flask · Flask-SQLAlchemy (SQLite) · Flask-Login · Jinja2 · Stripe · PayPal · SMTP · Vanilla JS · Leaflet

## Schnellstart

```bash
git clone https://github.com/dansparker/skyhop.git
cd skyhop
python -m venv .venv
# Windows: .venv\Scripts\activate   ·   macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env       # optional: SMTP- und Stripe-Zugangsdaten eintragen
flask --app run seed       # Demo-Daten anlegen
python run.py              # → http://localhost:5000
```

Ohne `.env` läuft alles im Demo-Modus: Zahlungen werden simuliert, E-Mails erscheinen unter
<http://localhost:5000/dev/mails>.

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
flask --app run cron       # alle periodischen Aufgaben (stündlich per Cron/Aufgabenplanung)
flask --app run payouts    # nur: vergangene Flüge abschließen + fällige Auszahlungen ausführen
flask --app run reset-db   # Datenbank leeren
```

### Konfiguration (Umgebungsvariablen / `.env`)

Alle Variablen mit Erklärung stehen in [`.env.example`](.env.example). Die wichtigsten:

| Variable                                   | Bedeutung                                                    |
|--------------------------------------------|--------------------------------------------------------------|
| `SKYHOP_SECRET_KEY`                        | Secret Key für Sessions und Token (in Produktion setzen!)    |
| `BASE_URL`                                 | Öffentliche URL – für Links in E-Mails und Stripe-Redirects  |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_USE_TLS`, `MAIL_DEFAULT_SENDER` | SMTP-Versand |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Stripe Checkout + Webhook                                  |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_MODE`, `PAYPAL_WEBHOOK_ID` | PayPal direkt (REST API v2) |
| `PAYMENT_PROVIDERS`                        | Angebotene Anbieter + Reihenfolge, z. B. `stripe,paypal`     |
| `PAYOUT_DELAY_HOURS`, `AUTO_COMPLETE_HOURS` | Haltefrist vor Auszahlung, automatischer Flugabschluss      |
| `UPLOAD_FOLDER`, `MAX_UPLOAD_MB`, `DOCUMENT_RETENTION_DAYS` | Upload-Ablage, Größenlimit, Löschfrist für Nachweise |
| `LEGAL_*`, `TERMS_VERSION`                 | Betreiberdaten für Impressum/Datenschutz/AGB, AGB-Version    |
| `DATABASE_URL`                             | SQLAlchemy-URL, Standard: `instance/skyhop.db`               |
| `TRUST_PROXY`                              | `1` hinter einem Reverse-Proxy (korrekte Client-IPs)         |

### Stripe einrichten (Testmodus)

1. Kostenloses Konto auf <https://dashboard.stripe.com> anlegen, Testmodus aktiv lassen.
2. Unter *Entwickler → API-Schlüssel* den **Secret Key** (`sk_test_…`) als `STRIPE_SECRET_KEY` eintragen.
3. Webhook lokal weiterleiten mit der [Stripe CLI](https://docs.stripe.com/stripe-cli):
   `stripe listen --forward-to localhost:5000/stripe/webhook` – das ausgegebene `whsec_…` als
   `STRIPE_WEBHOOK_SECRET` eintragen. In Produktion den Endpunkt `<BASE_URL>/stripe/webhook` im Dashboard
   anlegen (Events: `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `charge.refunded`).
4. Testkarte `4242 4242 4242 4242`, beliebiges Datum in der Zukunft, beliebige Prüfziffer.

### PayPal einrichten

**Variante 1 – PayPal über Stripe (empfohlen, kein Code):** Im Stripe-Dashboard unter
*Einstellungen → Zahlungsmethoden* PayPal aktivieren. Verfügbar für Stripe-Konten in EWR, UK und CH. PayPal
erscheint dann automatisch auf der Stripe-Bezahlseite; Erstattungen und Webhooks laufen über Stripe.

**Variante 2 – PayPal direkt:**

1. Unter <https://developer.paypal.com/dashboard/applications> eine App anlegen (Sandbox) und
   `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` eintragen, `PAYPAL_MODE=sandbox`.
2. Für die App einen Webhook auf `<BASE_URL>/paypal/webhook` anlegen (Events `CHECKOUT.ORDER.APPROVED`,
   `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.REFUNDED`) und dessen ID als `PAYPAL_WEBHOOK_ID` eintragen.
   Lokal braucht der Webhook eine öffentliche URL (z. B. per ngrok/Cloudflare Tunnel) – die Zahlung selbst
   funktioniert auch ohne, da beim Zurückkehren direkt abgebucht wird.
3. Mit einem Sandbox-Käuferkonto aus dem Developer-Dashboard bezahlen.
4. Für den Livebetrieb Live-Zugangsdaten eintragen und `PAYPAL_MODE=live` setzen.

Beide Varianten lassen sich kombinieren: `PAYMENT_PROVIDERS=stripe,paypal` zeigt beide Optionen,
`PAYMENT_PROVIDERS=paypal` nur PayPal direkt.

### Auszahlungen an Pilot:innen einrichten

- **Stripe Connect:** Im Stripe-Dashboard *Connect* aktivieren (Plattform-Profil ausfüllen). Pilot:innen starten
  unter *Auszahlungen* das Express-Onboarding. Überweisungen laufen als *Transfers* aus dem Plattform-Guthaben
  („separate charges and transfers“) – das Guthaben muss also verfügbar sein; sonst schlägt die Auszahlung fehl
  und wird beim nächsten Lauf wiederholt. Bitte im Testmodus prüfen, ob die gewählten Länder und die
  „recipient“-Servicevereinbarung für dein Plattform-Land unterstützt werden.
- **PayPal Payouts:** Muss für das PayPal-Geschäftskonto freigeschaltet sein (im Developer-Dashboard unter
  *App-Funktionen*). Der Status wird beim Cron-Lauf abgefragt.
- **Cron:** `flask --app run cron` stündlich ausführen (Linux: crontab, Windows: Aufgabenplanung) – erledigt
  Auszahlungen und löscht geprüfte Nachweise nach Ablauf der Frist.

> Hinweis zur Kasse: Zahlungen über Stripe landen im Stripe-Guthaben, PayPal-Zahlungen im PayPal-Guthaben.
> Wer beides anbietet, muss für ausreichend Guthaben auf dem jeweiligen Auszahlungsweg sorgen.

### E-Mail einrichten

Jeder SMTP-Anbieter funktioniert (z. B. Brevo, Mailjet, Postmark, Amazon SES oder das eigene Postfach).
Für die Zustellbarkeit SPF, DKIM und DMARC für die Absenderdomain einrichten. Lokal kann man mit
[Mailpit](https://mailpit.axllent.org) testen (`MAIL_SERVER=localhost`, `MAIL_PORT=1025`, `MAIL_USE_TLS=0`).

### Datenbank-Updates

Neue Spalten werden beim Start automatisch zu einer bestehenden SQLite-Datenbank hinzugefügt. Bereits
vorhandene Konten gelten dabei als bestätigt. Für Produktion mit PostgreSQL empfiehlt sich später
Flask-Migrate/Alembic.

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
