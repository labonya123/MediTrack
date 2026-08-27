"""
Production WSGI entry point — used by gunicorn (see Procfile), not by
`python run.py`. run.py is still the right way to run MediTrack locally
during development; this file exists only so a production server has a
plain `app` object to import, since gunicorn doesn't call Flask's
application-factory function for you.

    gunicorn wsgi:app

IMPORTANT — demo data seeding:
run.py always calls seed_all() for local dev convenience, which creates
fixed demo accounts (admin/admin123, dr_sharma/doctor123, etc.). That is
NOT safe to run unattended against a public production deployment — it
would put a known, guessable admin password on the internet. This entry
point only seeds if you explicitly opt in by setting SEED_DEMO_DATA=True,
which you should only ever do for a throwaway demo/staging deployment,
never a real one.
"""
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app

app = create_app()

if os.getenv('SEED_DEMO_DATA', 'False') == 'True':
    with app.app_context():
        try:
            from app.database.seed_data import seed_all
            seed_all()
        except Exception as e:
            print(f"Seed warning: {e}")
