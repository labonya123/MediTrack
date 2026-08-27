import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from config import DOCTOR_SESSION_MINUTES, MAX_LOGIN_ATTEMPTS, LOCKOUT_DURATION_MINUTES
from app.database.local_db import execute_query


def hash_password(password):
    """
    Hashes a password using SHA-256 with a random salt.
    The same password will produce different hashes each time (due to salt).
    This means even if the database is stolen, passwords cannot be recovered.

    Parameters:
        password - Plain text password string
    Returns:
        String in format "salt:hash" for storage
    """
    salt = secrets.token_hex(16)

    salted_password = f"{salt}{password}"
    hashed = hashlib.sha256(salted_password.encode('utf-8')).hexdigest()

    return f"{salt}:{hashed}"


def verify_password(plain_password, stored_hash):
    """
    Verifies a plain text password against a stored hash.
    Extracts the salt from the stored hash, re-hashes the input,
    and compares to check if password is correct.

    Parameters:
        plain_password - Password entered by user during login
        stored_hash    - The "salt:hash" string stored in database
    Returns:
        True if password is correct, False otherwise
    """
    try:
        salt, original_hash = stored_hash.split(':')

        salted_input = f"{salt}{plain_password}"
        input_hash = hashlib.sha256(salted_input.encode('utf-8')).hexdigest()

        return input_hash == original_hash
    except Exception:
        return False


def create_user(username, password, role):
    """
    Creates a new user account in the database.
    Validates that username is not already taken.

    Parameters:
        username - Chosen username (must be unique)
        password - Plain text password (will be hashed before storage)
        role     - 'patient', 'doctor', 'admin', or 'paramedic'
    Returns:
        Dictionary with 'success' True/False and 'user_id' or 'error' message
    """
    existing = execute_query(
        "SELECT user_id FROM users WHERE username = ?",
        (username,),
        fetchone=True
    )

    if existing:
        return {'success': False, 'error': 'Username already taken. Please choose another.'}

    allowed_roles = ['patient', 'doctor', 'admin', 'paramedic']
    if role not in allowed_roles:
        return {'success': False, 'error': f'Invalid role. Must be one of: {allowed_roles}'}

    user_id = str(uuid.uuid4())
    password_hash = hash_password(password)
    created_at = datetime.now().isoformat()

    execute_query(
        """INSERT INTO users (user_id, username, password_hash, role, is_active, created_at)
           VALUES (?, ?, ?, ?, 1, ?)""",
        (user_id, username, password_hash, role, created_at)
    )

    return {'success': True, 'user_id': user_id}


def authenticate_user(username, password, ip_address=None):
    """
    Verifies username and password for login, with simple brute-force
    lockout protection: after MAX_LOGIN_ATTEMPTS wrong passwords in a
    row, the account is locked for LOCKOUT_DURATION_MINUTES. A correct
    login resets the counter to 0.

    Parameters:
        username   - Entered username
        password   - Entered plain text password
        ip_address - Caller's IP, only used for the audit log entries
                      this function writes (failed attempt / locked) —
                      never logged alongside the password itself.
    Returns:
        (user_dict, status) tuple, where status is one of:
          'ok'      — login succeeded; user_dict has user_id/username/role
          'invalid' - wrong username OR wrong password. Deliberately the
                      SAME status either way — the login page shows one
                      generic message for both, so a failed attempt never
                      reveals whether the username exists.
          'locked'  - this account exists and is currently locked out.

    Note on unknown usernames: locking only applies to a username that
    matches a real account. There's nothing to lock — or log an audit
    entry for — when the username itself doesn't exist: audit_log.user_id
    is NOT NULL with a foreign key to users, so there's no valid id to
    write a row against. That's an existing constraint this respects
    rather than works around, and it also happens to be the right
    behaviour here — we don't want a wrong username to leave any kind of
    trace that would help an attacker distinguish it from a wrong password.
    """
    user = execute_query(
        "SELECT * FROM users WHERE username = ? AND is_active = 1",
        (username,),
        fetchone=True
    )

    if not user:
        return None, 'invalid'  # Unknown username — nothing to check, lock, or log

    if user['locked_until']:
        locked_until = datetime.fromisoformat(user['locked_until'])
        if datetime.now() < locked_until:
            return None, 'locked'
        execute_query(
            "UPDATE users SET locked_until = NULL, failed_login_attempts = 0 WHERE user_id = ?",
            (user['user_id'],)
        )
        user = dict(user)
        user['failed_login_attempts'] = 0

    if not verify_password(password, user['password_hash']):
        attempts = (user['failed_login_attempts'] or 0) + 1

        if attempts >= MAX_LOGIN_ATTEMPTS:
            locked_until = (datetime.now() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)).isoformat()
            execute_query(
                "UPDATE users SET failed_login_attempts = ?, locked_until = ? WHERE user_id = ?",
                (attempts, locked_until, user['user_id'])
            )
            log_audit(user['user_id'], user['role'], 'ACCOUNT_LOCKED',
                      details=f"Account locked for {LOCKOUT_DURATION_MINUTES} minutes after "
                              f"{attempts} failed login attempts",
                      ip_address=ip_address)
            return None, 'locked'
        else:
            execute_query(
                "UPDATE users SET failed_login_attempts = ? WHERE user_id = ?",
                (attempts, user['user_id'])
            )
            log_audit(user['user_id'], user['role'], 'LOGIN_FAILED',
                      details=f"Failed login attempt {attempts}/{MAX_LOGIN_ATTEMPTS}",
                      ip_address=ip_address)
            return None, 'invalid'

    execute_query(
        "UPDATE users SET last_login = ?, failed_login_attempts = 0, locked_until = NULL WHERE user_id = ?",
        (datetime.now().isoformat(), user['user_id'])
    )

    return {
        'user_id': user['user_id'],
        'username': user['username'],
        'role': user['role']
    }, 'ok'


def get_user_by_id(user_id):
    """
    Retrieves user information by their user ID.
    Used to load user data from session.

    Parameters:
        user_id - The UUID of the user
    Returns:
        User dictionary without password hash, or None if not found
    """
    user = execute_query(
        "SELECT user_id, username, role, is_active, created_at, last_login FROM users WHERE user_id = ?",
        (user_id,),
        fetchone=True
    )
    return user

def create_doctor_session(doctor_user_id, patient_id):
    """
    Creates a new 15-minute doctor access session when a doctor scans a patient QR code.
    Any existing active session for this doctor+patient is first deactivated.

    Parameters:
        doctor_user_id - The doctor's user ID
        patient_id     - The patient whose QR was scanned
    Returns:
        Dictionary with session_id and expires_at time
    """
    execute_query(
        "UPDATE doctor_sessions SET is_active = 0 WHERE doctor_user_id = ? AND is_active = 1",
        (doctor_user_id,)
    )

    started_at = datetime.now()
    expires_at = started_at + timedelta(minutes=DOCTOR_SESSION_MINUTES)

    session_id = str(uuid.uuid4())

    execute_query(
        """INSERT INTO doctor_sessions (session_id, doctor_user_id, patient_id, started_at, expires_at, is_active)
           VALUES (?, ?, ?, ?, ?, 1)""",
        (session_id, doctor_user_id, patient_id,
         started_at.isoformat(), expires_at.isoformat())
    )

    return {
        'session_id': session_id,
        'expires_at': expires_at.isoformat(),
        'minutes_remaining': DOCTOR_SESSION_MINUTES
    }


def validate_doctor_session(doctor_user_id, patient_id):
    """
    Checks if a doctor currently has a valid (non-expired) session for a patient.
    Auto-expires sessions that have passed their time limit.

    Parameters:
        doctor_user_id - The doctor's user ID
        patient_id     - The patient they want to access
    Returns:
        Dictionary with 'valid' True/False and 'minutes_remaining' if valid
    """
    session = execute_query(
        """SELECT * FROM doctor_sessions
           WHERE doctor_user_id = ? AND patient_id = ? AND is_active = 1
           ORDER BY started_at DESC LIMIT 1""",
        (doctor_user_id, patient_id),
        fetchone=True
    )

    if not session:
        return {'valid': False, 'reason': 'No active session. Please scan patient QR code.'}

    expires_at = datetime.fromisoformat(session['expires_at'])
    now = datetime.now()

    if now > expires_at:
        execute_query(
            "UPDATE doctor_sessions SET is_active = 0 WHERE session_id = ?",
            (session['session_id'],)
        )
        return {'valid': False, 'reason': 'Session expired. Please scan patient QR code again.'}

    remaining = expires_at - now
    minutes_remaining = int(remaining.total_seconds() / 60)
    seconds_remaining = int(remaining.total_seconds() % 60)

    return {
        'valid': True,
        'session_id': session['session_id'],
        'minutes_remaining': minutes_remaining,
        'seconds_remaining': seconds_remaining,
        'expires_at': session['expires_at']
    }


def log_audit(user_id, user_role, action, target_patient_id=None, details=None, ip_address=None):
    """
    Records every data access action to the audit log.
    This creates an accountability trail — we always know who accessed what and when.

    Parameters:
        user_id           - Who performed the action
        user_role         - Their role (doctor, admin, etc.)
        action            - Description of what they did
        target_patient_id - Which patient's data was accessed (if any)
        details           - Any extra details to record
        ip_address        - IP address of the request
    """
    audit_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat()

    execute_query(
        """INSERT INTO audit_log (audit_id, user_id, user_role, action, target_patient_id, details, ip_address, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (audit_id, user_id, user_role, action, target_patient_id, details, ip_address, timestamp)
    )
