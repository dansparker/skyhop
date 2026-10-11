# Skyhop online bringen

Es gibt zwei Wege:

| | **A – Shared Hosting** | **B – Eigener Server (VPS) mit Docker** |
|---|---|---|
| Für | Webhosting-Pakete mit „Python App“ (cPanel, Plesk) | Root-Server/VPS (Hetzner, Netcup, …) |
| Datenbank | MySQL/MariaDB aus dem Hosting-Paket | PostgreSQL (im Docker-Stack enthalten) |
| HTTPS | über das Panel (Let's Encrypt / AutoSSL) | automatisch über Caddy |
| Hintergrundjobs | Cronjob im Panel | eigener Container |

> **Docker läuft auf Shared Hosting praktisch nie** (kein Root-Zugriff). Für Shared Hosting gilt Weg A.

---

## A – Shared Hosting (cPanel / Plesk)

### Voraussetzungen prüfen

Im Hosting-Panel sollte es Folgendes geben – sonst beim Hoster nachfragen:

- [ ] **„Setup Python App“** (cPanel) bzw. **„Python“** (Plesk) mit **Python 3.10 oder neuer**
- [ ] **SSH-Zugang** oder ein **Terminal** im Panel
- [ ] **MySQL/MariaDB-Datenbank** anlegen können
- [ ] **Cronjobs**
- [ ] **E-Mail-Postfach** (für den Versand von Bestätigungsmails)
- [ ] **SSL-Zertifikat** (Let's Encrypt/AutoSSL)

### 1. Adresse festlegen (ohne eigene Domain)

Ohne eigene Domain bekommst du meist eine Adresse vom Hoster, z. B. `deinname.hoster.at` oder eine
Test-/Vorschau-Subdomain. Lege im Panel eine **Subdomain** an (z. B. `skyhop.deinname.hoster.at`) – auf diese
URL zeigt später die App. Eine eigene Domain kannst du jederzeit nachrüsten; dann nur `BASE_URL` ändern.

### 2. Datenbank anlegen

Im Panel unter *MySQL-Datenbanken*: Datenbank + Benutzer anlegen, dem Benutzer **alle Rechte** auf die
Datenbank geben. Notiere Datenbankname, Benutzer und Passwort (cPanel setzt oft ein Präfix, z. B.
`deinname_skyhop`).

### 3. Code auf den Server bringen

Per SSH/Terminal im Home-Verzeichnis (**nicht** in `public_html`!):

```bash
git clone https://github.com/dansparker/skyhop.git ~/skyhop
```

Alternativ: ZIP von GitHub herunterladen und im Datei-Manager nach `~/skyhop` entpacken.

### 4. Python-App im Panel anlegen

**cPanel → Setup Python App → Create Application**

| Feld | Wert |
|---|---|
| Python version | 3.10 oder neuer (höchste verfügbare) |
| Application root | `skyhop` |
| Application URL | deine Subdomain/Domain |
| Application startup file | `passenger_wsgi.py` |
| Application Entry point | `application` |

Nach dem Anlegen zeigt das Panel oben einen Befehl wie
`source /home/deinname/virtualenv/skyhop/3.11/bin/activate && cd /home/deinname/skyhop` – den brauchst du gleich.

**Plesk:** *Websites & Domains → Python* (bzw. „Phusion Passenger“): Anwendungsstamm `skyhop`,
Startdatei `passenger_wsgi.py`.

### 5. Installationsskript ausführen

```bash
source /home/deinname/virtualenv/skyhop/3.11/bin/activate && cd ~/skyhop
bash deploy/shared-hosting/install.sh
```

Beim ersten Lauf legt das Skript die Datei `.env` mit einem sicheren Secret Key an und hält an. Trage dann in
`.env` ein (`nano .env` oder Datei-Manager):

```ini
SKYHOP_ENV=production
BASE_URL=https://skyhop.deinname.hoster.at
DATABASE_URL=mysql://deinname_skyhop:DB-PASSWORT@localhost/deinname_skyhop

MAIL_SERVER=mail.deinname.hoster.at      # steht in den Postfach-Einstellungen des Hosters
MAIL_PORT=587
MAIL_USE_TLS=1
MAIL_USERNAME=noreply@deinname.hoster.at
MAIL_PASSWORD=POSTFACH-PASSWORT
MAIL_DEFAULT_SENDER=noreply@deinname.hoster.at

LEGAL_NAME=…                              # Betreiberdaten für Impressum/Datenschutz/AGB
LEGAL_ADDRESS=…
LEGAL_EMAIL=…
LEGAL_HOSTING=Name des Hosters, Ort, Land
LEGAL_MAIL_PROVIDER=Name des Hosters, Ort, Land
```

> Sonderzeichen im Datenbank-Passwort (`@ : / # ?`) müssen in der URL kodiert werden, z. B. `@` → `%40`.

Dann das Skript **noch einmal** starten. Es installiert alles, richtet die Datenbank ein, fragt nach deinem
**Admin-Konto** und startet die App neu.

### 6. HTTPS, Cronjob, Test

1. **SSL** im Panel für die Subdomain aktivieren (*SSL/TLS Status → Run AutoSSL* bzw. Let's Encrypt), danach
   „HTTPS erzwingen“ einschalten (oder `deploy/shared-hosting/.htaccess.example` nutzen).
2. **Cronjob** (stündlich) – den genauen Befehl gibt das Installationsskript am Ende aus, z. B.:
   ```
   5 * * * *  cd /home/deinname/skyhop && /home/deinname/virtualenv/skyhop/3.11/bin/flask --app wsgi cron >> /home/deinname/skyhop/instance/cron.log 2>&1
   ```
3. Seite aufrufen, mit dem Admin-Konto anmelden, eine Testregistrierung machen (Bestätigungsmail muss ankommen).

### 7. Zahlungen verbinden

- **Stripe:** Webhook-Endpunkt `https://<deine-adresse>/stripe/webhook` im Dashboard anlegen, Keys in `.env`.
- **PayPal:** Webhook `https://<deine-adresse>/paypal/webhook` anlegen, Zugangsdaten + `PAYPAL_WEBHOOK_ID` in `.env`.
- Nach jeder Änderung an `.env`: `touch ~/skyhop/tmp/restart.txt` (oder im Panel „Restart“).

### Updates

```bash
source /home/deinname/virtualenv/skyhop/3.11/bin/activate && cd ~/skyhop
bash deploy/shared-hosting/update.sh
```

### Fehlersuche

| Problem | Lösung |
|---|---|
| „Incomplete response“ / 500 | Fehlerlog im Panel bzw. `~/skyhop/stderr.log` ansehen |
| `SKYHOP_SECRET_KEY muss in Produktion gesetzt sein` | Secret Key in `.env` fehlt oder ist zu kurz |
| `Access denied for user` | `DATABASE_URL` prüfen (Präfix, Passwort kodiert, Rechte vergeben) |
| Keine Bestätigungsmails | `MAIL_*` prüfen; Absender muss ein echtes Postfach beim Hoster sein |
| Änderungen wirken nicht | `touch tmp/restart.txt` |
| Uploads schlagen fehl | Upload-Limit im Panel/PHP-Einstellungen ist hier egal – aber Speicherplatz prüfen; Ordner `instance/uploads` muss beschreibbar sein |

### Backups

Sichere regelmäßig die **Datenbank** (Panel → Backup bzw. phpMyAdmin-Export) und den Ordner
**`~/skyhop/instance/uploads`** sowie die Datei **`.env`**.

---

## B – Eigener Server mit Docker

Voraussetzung: Linux-Server mit Docker und Docker Compose, Ports 80/443 offen.

```bash
git clone https://github.com/dansparker/skyhop.git && cd skyhop
cp .env.example .env
nano .env            # SKYHOP_SECRET_KEY, POSTGRES_PASSWORD, BASE_URL, DOMAIN, MAIL_*, LEGAL_* …
docker compose up -d --build
docker compose exec app flask --app wsgi create-admin
```

- **Mit Domain:** DNS-A-Record auf die Server-IP, `DOMAIN=skyhop.example.at`, `BASE_URL=https://skyhop.example.at`
  → Caddy holt das Zertifikat automatisch.
- **Ohne Domain:** `DOMAIN=:80`, `BASE_URL=http://<server-ip>` (nur zum Testen – ohne HTTPS keine echten
  Zahlungen/Logins verwenden).
- Hintergrundjobs laufen im Container `cron`; Uploads, Datenbank und Zertifikate liegen in Docker-Volumes.
- Update: `git pull && docker compose up -d --build`
- Backup: `docker compose exec db pg_dump -U skyhop skyhop > backup.sql` und das Volume `uploads`.

---

## Checkliste vor dem Livegang

- [ ] `SKYHOP_ENV=production`, langer `SKYHOP_SECRET_KEY`
- [ ] HTTPS aktiv, `BASE_URL` beginnt mit `https://`
- [ ] E-Mail-Versand getestet (Registrierung, Passwort vergessen)
- [ ] Rechtstexte ausgefüllt (keine gelben „[… ergänzen]“-Markierungen) und anwaltlich geprüft
- [ ] Stripe/PayPal zuerst im Test-/Sandbox-Modus, dann Live-Keys
- [ ] Webhooks eingerichtet
- [ ] Cronjob läuft (`instance/cron.log`)
- [ ] Backups eingerichtet
- [ ] Demo-Daten **nicht** importiert (`flask seed` nur lokal!)
