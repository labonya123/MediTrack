from flask import Flask, request, redirect
from datetime import timedelta
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import SECRET_KEY, LOCAL_UPLOAD_FOLDER, PERMANENT_SESSION_LIFETIME, DEBUG


def create_app():
    """
    Flask application factory.
    Creates the app, initialises the database, registers all blueprints,
    and starts the background sync thread if cloud is enabled.
    """
    app = Flask(__name__)

    app.secret_key = SECRET_KEY
    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB
    app.config['UPLOAD_FOLDER'] = LOCAL_UPLOAD_FOLDER
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=PERMANENT_SESSION_LIFETIME)
    app.config['DEBUG'] = DEBUG

    app.config['SESSION_COOKIE_HTTPONLY'] = True   
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  
    app.config['SESSION_COOKIE_SECURE'] = not DEBUG

    _configure_production_hardening(app)

    from app.database.local_db import init_db, add_missing_columns
    with app.app_context():
        init_db()
        add_missing_columns()

    with app.app_context():
        _backfill_qr_tokens()

    from app.routes.auth       import auth_bp
    from app.routes.patient    import patient_bp
    from app.routes.doctor     import doctor_bp
    from app.routes.admin      import admin_bp
    from app.routes.paramedic  import paramedic_bp
    from app.routes.admin_sync import admin_sync_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(patient_bp)
    app.register_blueprint(doctor_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(paramedic_bp)
    app.register_blueprint(admin_sync_bp)  

    os.makedirs(LOCAL_UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(os.path.join(LOCAL_UPLOAD_FOLDER, 'qr_codes'), exist_ok=True)
    os.makedirs(os.path.join(LOCAL_UPLOAD_FOLDER, 'reports'), exist_ok=True)

    from app.services.sync_service import start_background_sync
    start_background_sync()

    return app


def _configure_production_hardening(app):
    """
    Adds HTTPS enforcement and standard security response headers, but
    ONLY when DEBUG is False. These are meaningless (and sometimes
    actively annoying) during local development, so they're skipped
    entirely in dev — this only changes behaviour in a production
    deployment (e.g. Render.com).

    Render (like most PaaS hosts) terminates TLS at its own load balancer
    and forwards plain HTTP to the app, setting X-Forwarded-Proto to tell
    us the original scheme. That's why this checks that header instead of
    request.is_secure, which would always report False behind such a proxy.
    """
    if DEBUG:
        return

    @app.before_request
    def _enforce_https():
        forwarded_proto = request.headers.get('X-Forwarded-Proto', '')
        if forwarded_proto and forwarded_proto != 'https':
            url = request.url.replace('http://', 'https://', 1)
            return redirect(url, code=301)

    @app.after_request
    def _add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response


def _backfill_qr_tokens():
    """
    Generates and stores qr_token for any patient that doesn't have one yet.
    Runs at startup — idempotent and fast (only touches rows where token is NULL).
    """
    from app.database.local_db import execute_query
    from app.services.qr_service import generate_patient_token

    patients = execute_query(
        "SELECT patient_id FROM patients WHERE qr_token IS NULL",
        fetch=True
    )
    if not patients:
        return

    for p in patients:
        pid = p['patient_id']
        token = generate_patient_token(pid)
        execute_query(
            "UPDATE patients SET qr_token = ? WHERE patient_id = ?",
            (token, pid)
        )
    print(f"  Backfilled qr_token for {len(patients)} patient(s)")