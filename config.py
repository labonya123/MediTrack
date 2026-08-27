import os
import secrets
import warnings
from dotenv import load_dotenv

load_dotenv()

USE_CLOUD = os.getenv('USE_CLOUD', 'False') == 'True'

LOCAL_DB_PATH = os.path.join(os.path.dirname(__file__), 'meditrack_local.db')

SUPABASE_URL = os.getenv('SUPABASE_URL', '')
SUPABASE_KEY = os.getenv('SUPABASE_KEY', '')


LOCAL_UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'app', 'static', 'uploads')
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
MAX_UPLOAD_SIZE_MB = 10


DEBUG = os.getenv('DEBUG', 'True') == 'True'
HOST = '0.0.0.0'
PORT = int(os.getenv('PORT', '5000'))
APP_NAME = 'MediTrack'
VERSION = '3.0.0 - Cloud Sync'


def _require_secret(env_name, min_length=16):
    value = os.getenv(env_name, '')
    if value and len(value) >= min_length:
        return value

    if not DEBUG:
        raise RuntimeError(
            f"{env_name} is not set (or is too short — need >= {min_length} chars). "
            f"Set it as an environment variable before starting MediTrack in production. "
            f"Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )

    generated = secrets.token_hex(32)
    warnings.warn(
        f"{env_name} is not set in .env — using a random development-only key for this "
        f"run. This is fine for local testing, but sessions/encrypted data won't survive "
        f"a restart. Set {env_name} in your .env file to avoid this.",
        stacklevel=2
    )
    return generated


SECRET_KEY = _require_secret('SECRET_KEY')
ENCRYPTION_KEY = _require_secret('ENCRYPTION_KEY')

DOCTOR_SESSION_MINUTES = 15
PERMANENT_SESSION_LIFETIME = 60

APP_BASE_URL = os.getenv('APP_BASE_URL', 'http://localhost:5000')

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 5

SYNC_INTERVAL_SECONDS = int(os.getenv('SYNC_INTERVAL_SECONDS', '45'))  # default: 45 seconds

OUTBREAK_CLUSTER_THRESHOLD = int(os.getenv('OUTBREAK_CLUSTER_THRESHOLD', '3'))