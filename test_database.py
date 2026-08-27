import os
import tempfile
import pytest

import app.database.local_db as local_db
from app.database.local_db import init_db, execute_query
from app.services.auth_service import (
    hash_password,
    verify_password,
    create_user,
    authenticate_user,
)
from config import MAX_LOGIN_ATTEMPTS


@pytest.fixture
def temp_db(monkeypatch):
    """
    Creates a brand-new, empty SQLite database file in a temp folder,
    points MediTrack's database layer at it (instead of the real
    meditrack_local.db), initialises the schema, and cleans up
    afterwards.

    Every test function that includes `temp_db` as an argument gets
    its OWN fresh database — tests never see each other's data.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    # local_db.py does `from config import LOCAL_DB_PATH`, so the name
    # lives inside the local_db module itself — patch it there.
    monkeypatch.setattr(local_db, "LOCAL_DB_PATH", path)

    init_db()  # creates all tables (users, patients, etc.) in the temp file

    yield path

    os.remove(path)


# ---------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------

def test_hash_password_produces_different_hash_each_time():
    """Same password hashed twice should NOT look identical (random salt)."""
    hash1 = hash_password("MySecret123")
    hash2 = hash_password("MySecret123")
    assert hash1 != hash2


def test_verify_password_accepts_correct_password():
    stored_hash = hash_password("MySecret123")
    assert verify_password("MySecret123", stored_hash) is True


def test_verify_password_rejects_wrong_password():
    stored_hash = hash_password("MySecret123")
    assert verify_password("WrongPassword", stored_hash) is False


# ---------------------------------------------------------------------
# User creation
# ---------------------------------------------------------------------

def test_create_user_succeeds_with_valid_data(temp_db):
    result = create_user("test_patient1", "Password123", "patient")
    assert result["success"] is True
    assert "user_id" in result


def test_create_user_rejects_duplicate_username(temp_db):
    create_user("duplicate_user", "Password123", "patient")
    result = create_user("duplicate_user", "AnotherPassword", "patient")
    assert result["success"] is False
    assert "already taken" in result["error"].lower()


def test_create_user_rejects_invalid_role(temp_db):
    result = create_user("test_patient2", "Password123", "not_a_real_role")
    assert result["success"] is False


# ---------------------------------------------------------------------
# Login (authenticate_user)
# ---------------------------------------------------------------------

def test_login_succeeds_with_correct_credentials(temp_db):
    create_user("login_test_user", "CorrectPass1", "patient")

    user, status = authenticate_user("login_test_user", "CorrectPass1")

    assert status == "ok"
    assert user["username"] == "login_test_user"


def test_login_fails_with_wrong_password(temp_db):
    create_user("login_test_user2", "CorrectPass1", "patient")

    user, status = authenticate_user("login_test_user2", "WrongPassword")

    assert status == "invalid"
    assert user is None


def test_login_fails_with_unknown_username(temp_db):
    user, status = authenticate_user("no_such_user", "AnyPassword")

    assert status == "invalid"
    assert user is None


# ---------------------------------------------------------------------
# Brute-force lockout
# ---------------------------------------------------------------------

def test_account_locks_after_max_failed_attempts(temp_db):
    """
    MediTrack should lock an account after MAX_LOGIN_ATTEMPTS wrong
    passwords in a row (see config.py). This test deliberately fails
    the login MAX_LOGIN_ATTEMPTS times, then checks the account is
    locked even when the CORRECT password is used on the next try.
    """
    create_user("lockout_test_user", "CorrectPass1", "patient")

    for attempt in range(MAX_LOGIN_ATTEMPTS):
        user, status = authenticate_user("lockout_test_user", "WrongPassword")

    # After enough failed attempts, the account should now be locked —
    # even a CORRECT password should be rejected until the lockout expires.
    user, status = authenticate_user("lockout_test_user", "CorrectPass1")
    assert status == "locked"
    assert user is None


def test_failed_attempts_reset_after_successful_login(temp_db):
    create_user("reset_test_user", "CorrectPass1", "patient")

    # Two wrong attempts (not enough to lock the account)
    authenticate_user("reset_test_user", "WrongPassword")
    authenticate_user("reset_test_user", "WrongPassword")

    # Then a correct login should succeed and reset the counter
    user, status = authenticate_user("reset_test_user", "CorrectPass1")
    assert status == "ok"


# ---------------------------------------------------------------------
# Schema / database integrity
# ---------------------------------------------------------------------

def test_users_table_exists_after_init(temp_db):
    tables = execute_query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='users'",
        fetch=True,
    )
    assert len(tables) == 1


def test_foreign_key_constraint_is_enforced(temp_db):
    """
    patients.user_id has a FOREIGN KEY reference to users(user_id).
    Inserting a patient row with a user_id that doesn't exist in the
    users table should be rejected by SQLite, proving referential
    integrity is actually being enforced (not just declared).

    All other NOT NULL columns are filled in here so that, if this
    test fails, it can only be because of the foreign key — not
    because some unrelated required field was left empty.
    """
    with pytest.raises(Exception):
        execute_query(
            """INSERT INTO patients
               (patient_id, user_id, first_name, last_name, gender, date_of_birth)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "fake-patient-id",
                "user-id-that-does-not-exist",
                "Test",
                "Patient",
                "Other",
                "2000-01-01",
            ),
        )