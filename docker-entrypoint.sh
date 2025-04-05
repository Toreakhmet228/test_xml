#!/bin/bash
for i in {1..30}; do
    if nc -z postgres 5432; then
        echo "PostgreSQL is ready!"
        break
    fi
    echo "Waiting for PostgreSQL... ($i/30)"
    sleep 1
done
if [ $i -eq 30 ]; then
    exit 1
fi

python manage.py makemigrations
python manage.py migrate

case "$1" in
    "backend")
        gunicorn valxml.wsgi:application --bind 0.0.0.0:8000
        ;;
    "celery")
        celery -A valxml worker --loglevel=info --concurrency=4
        ;;
    *)
        exit 1
        ;;
esac