#!/bin/sh
# core-api container entrypoint: migrate (idempotent), then serve.
# Kept as a real entry point rather than inlined in docker-compose.yml so
# local `docker build && docker run` behaves the same as compose.
set -e

echo "core-api: waiting for database..."
python manage.py wait_for_db

echo "core-api: applying migrations..."
python manage.py migrate --noinput

if [ "${DJANGO_AUTO_SEED_DEMO:-false}" = "true" ]; then
    echo "core-api: seeding demo data (DJANGO_AUTO_SEED_DEMO=true)..."
    python manage.py seed_demo || true
fi

echo "core-api: starting gunicorn..."
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 60
