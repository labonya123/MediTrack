# --workers 1 is intentional, not a typo: create_app() starts an in-process
# background sync thread. Every gunicorn WORKER is a separate process that
# would each start its own duplicate sync thread, all contending over the
# same local SQLite file. --threads gives request concurrency within that
# single process instead, without duplicating the sync thread.
web: gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 60
