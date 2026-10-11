#!/bin/sh
# Create/upgrade the schema once before the workers start (avoids races between Gunicorn workers).
set -e
flask --app wsgi init-db
exec "$@"
