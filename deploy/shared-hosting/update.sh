#!/usr/bin/env bash
# Skyhop auf Shared Hosting aktualisieren (neuen Code holen, Abhängigkeiten, Datenbank, Neustart).
#   source <pfad-zur-virtualenv>/bin/activate
#   bash deploy/shared-hosting/update.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$APP_DIR"

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
  echo "Bitte zuerst die virtuelle Umgebung aktivieren (Befehl aus dem Hosting-Panel)." >&2
  exit 1
fi

if [[ -d .git ]]; then
  echo "==> Hole neuen Code"
  git pull --ff-only
else
  echo "==> Kein Git-Repository – neuen Code bitte vorher hochladen (ohne .env und instance/ zu überschreiben)."
fi

echo "==> Abhängigkeiten"
pip install -r requirements.txt

echo "==> Datenbank aktualisieren"
flask --app wsgi init-db

echo "==> Neustart"
mkdir -p tmp
touch tmp/restart.txt
echo "Fertig."
