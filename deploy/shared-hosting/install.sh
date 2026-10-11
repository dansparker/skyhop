#!/usr/bin/env bash
# Erstinstallation von Skyhop auf Shared Hosting (cPanel/Plesk „Python App“ mit Passenger).
#
# Aufruf im Terminal/SSH des Hostings, im App-Verzeichnis:
#   source <pfad-zur-virtualenv>/bin/activate     # Befehl zeigt dir das Panel unter „Setup Python App“ an
#   bash deploy/shared-hosting/install.sh
#
# Das Skript ist idempotent – du kannst es gefahrlos erneut ausführen.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$APP_DIR"

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m%s\033[0m\n' "$*"; }

say "Prüfe Python-Umgebung"
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
  warn "Keine virtuelle Umgebung aktiv. Bitte zuerst den 'source …/bin/activate'-Befehl aus dem Hosting-Panel ausführen."
  exit 1
fi
python - <<'PY'
import sys
if sys.version_info < (3, 10):
    sys.exit(f"Python {sys.version.split()[0]} ist zu alt – bitte im Panel Python 3.10 oder neuer wählen.")
print(f"Python {sys.version.split()[0]} in {sys.prefix}")
PY

say "Installiere Abhängigkeiten"
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

if [[ ! -f .env ]]; then
  say "Lege .env an"
  cp .env.example .env
  SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
  python - "$SECRET" <<'PY'
import re, sys
secret = sys.argv[1]
s = open(".env", encoding="utf-8").read()
s = re.sub(r"^SKYHOP_SECRET_KEY=.*$", f"SKYHOP_SECRET_KEY={secret}", s, flags=re.M)
s = re.sub(r"^SKYHOP_ENV=.*$", "SKYHOP_ENV=production", s, flags=re.M)
open(".env", "w", encoding="utf-8").write(s)
PY
  chmod 600 .env
  warn "Bitte jetzt .env bearbeiten (mindestens BASE_URL, DATABASE_URL und MAIL_*) und das Skript erneut starten."
  warn "  nano .env      (oder im Datei-Manager des Hostings)"
  exit 0
fi
chmod 600 .env

say "Prüfe Konfiguration"
python - <<'PY'
from dotenv import dotenv_values
cfg = dotenv_values(".env")
problems = []
if cfg.get("SKYHOP_ENV") != "production":
    problems.append("SKYHOP_ENV=production fehlt")
if not cfg.get("BASE_URL"):
    problems.append("BASE_URL fehlt (z. B. https://deinname.hoster.at)")
if not cfg.get("DATABASE_URL"):
    print("Hinweis: DATABASE_URL leer → SQLite in instance/skyhop.db (ok für den Start, MySQL empfohlen)")
if not cfg.get("MAIL_SERVER"):
    print("Hinweis: MAIL_SERVER leer → es werden KEINE E-Mails verschickt (Registrierung braucht Bestätigungsmails!)")
if problems:
    raise SystemExit("Bitte in .env ergänzen: " + "; ".join(problems))
print("ok")
PY

say "Richte Datenbank ein"
flask --app wsgi init-db

mkdir -p instance/uploads tmp
chmod 700 instance instance/uploads

if [[ "${SKIP_ADMIN:-0}" != "1" ]]; then
  say "Admin-Konto anlegen (Abbrechen mit Strg+C, falls schon vorhanden)"
  flask --app wsgi create-admin || true
fi

say "Starte App neu"
touch tmp/restart.txt

cat <<EOF

$(printf '\033[1;32m')Fertig!$(printf '\033[0m')

Letzte Schritte im Hosting-Panel:
  1. Cronjob anlegen (stündlich, z. B. Minute 5):
       cd $APP_DIR && $VIRTUAL_ENV/bin/flask --app wsgi cron >> $APP_DIR/instance/cron.log 2>&1
  2. SSL/HTTPS für die Domain aktivieren (Let's Encrypt / AutoSSL) und BASE_URL auf https:// setzen.
  3. Seite aufrufen und mit dem Admin-Konto anmelden.

Updates später mit:  bash deploy/shared-hosting/update.sh
EOF
