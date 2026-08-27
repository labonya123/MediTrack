import os
import sys
import socket
import threading
import json
import traceback
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from config import (
    USE_CLOUD, SUPABASE_URL, SUPABASE_KEY,
    SYNC_INTERVAL_SECONDS, LOCAL_UPLOAD_FOLDER
)
from app.database.local_db import execute_query, assert_safe_identifier

SYNC_TABLES = [
    ('users',               'user_id'),
    ('patients',            'patient_id'),
    ('patient_diseases',    'patient_disease_id'),
    ('patient_allergies',   'patient_allergy_id'),
    ('patient_medications', 'patient_medication_id'),
    ('hospitalizations',    'hospitalization_id'),
    ('surgeries',           'surgery_id'),
    ('emergency_contacts',  'contact_id'),
    ('prescriptions',       'prescription_id'),
    ('medical_reports',     'report_id'),   # files handled separately
]

REFERENCE_TABLES = [
    ('disease_categories',  'disease_category_id'),
    ('disease_master',      'disease_id'),
    ('allergy_categories',  'allergy_category_id'),
    ('allergy_master',      'allergy_id'),
    ('medication_master',   'medication_id'),
]
NO_SYNC_TABLES = {name for name, _ in REFERENCE_TABLES}

STORAGE_BUCKET = 'medical-reports'

_sync_thread = None
_stop_event = threading.Event()
_wake_event = threading.Event()



def check_internet():
    if not SUPABASE_URL:
        return False
    try:
        import requests
        requests.get(
            SUPABASE_URL + '/rest/v1/',
            headers={'apikey': SUPABASE_KEY},
            timeout=5
        )
        return True
    except Exception:
        return False
  


def get_supabase_client():
    """
    Returns a Supabase client, or None if not configured / unavailable.
    Call this fresh each time — do not cache the client module-level.
    """
    if not USE_CLOUD or not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        from supabase import create_client
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        return None


def get_sync_status():
    """
    Returns a dict describing the current sync state for the UI.
    Counts pending records per table for the dashboard breakdown.
    """
    pending_by_table = {}
    total_pending = 0

    for table, _ in SYNC_TABLES:
        assert_safe_identifier(table)  

        try:
            result = execute_query(
                f"SELECT COUNT(*) as cnt FROM {table} WHERE sync_status IN ('pending', 'syncing')",
                fetchone=True
            )
            count = result.get('cnt', 0) if result else 0
            if count > 0:
                pending_by_table[table] = count
            total_pending += count
        except Exception:
            pass   

    error_count = 0
    for table, _ in SYNC_TABLES:
        assert_safe_identifier(table) 
        try:
            result = execute_query(
                f"SELECT COUNT(*) as cnt FROM {table} WHERE sync_status = 'error'",
                fetchone=True
            )
            error_count += result.get('cnt', 0) if result else 0
        except Exception:
            pass

    last_sync = execute_query(
        "SELECT synced_at FROM sync_logs WHERE status = 'success' ORDER BY synced_at DESC LIMIT 1",
        fetchone=True
    )
    last_sync_time = last_sync.get('synced_at') if last_sync else None

    if not USE_CLOUD:
        return {
            'status': 'disabled',
            'message': 'Cloud sync not configured (Phase 1 — Local Mode)',
            'icon': '💾',
            'online': False,
            'pending_count': total_pending,
            'error_count': error_count,
            'pending_by_table': pending_by_table,
            'last_sync_time': last_sync_time,
        }

    if not check_internet():
        return {
            'status': 'offline',
            'message': f'Offline — {total_pending} records waiting',
            'icon': '🔴',
            'online': False,
            'pending_count': total_pending,
            'error_count': error_count,
            'pending_by_table': pending_by_table,
            'last_sync_time': last_sync_time,
        }

    if total_pending == 0 and error_count == 0:
        return {
            'status': 'synced',
            'message': 'All data synced ✓',
            'icon': '✅',
            'online': True,
            'pending_count': 0,
            'error_count': 0,
            'pending_by_table': {},
            'last_sync_time': last_sync_time,
        }

    if error_count > 0:
        return {
            'status': 'error',
            'message': f'{error_count} records failed to sync — will retry',
            'icon': '⚠️',
            'online': True,
            'pending_count': total_pending,
            'error_count': error_count,
            'pending_by_table': pending_by_table,
            'last_sync_time': last_sync_time,
        }

    return {
        'status': 'pending',
        'message': f'{total_pending} records ready to sync',
        'icon': '🔄',
        'online': True,
        'pending_count': total_pending,
        'error_count': error_count,
        'pending_by_table': pending_by_table,
        'last_sync_time': last_sync_time,
    }


def _upload_report_file(supabase, report):
    """
    Uploads a medical report file to Supabase Storage.
    Returns the public URL on success, None on failure.
    """
    local_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'app', 'static', report.get('file_path', '')
    )

    if not os.path.exists(local_path):
        return None

    storage_path = f"{report['patient_id']}/{report['report_id']}_{report['file_name']}"

    try:
        with open(local_path, 'rb') as f:
            file_bytes = f.read()

        ext = report.get('file_type', 'jpg').lower()
        mime_map = {'pdf': 'application/pdf', 'png': 'image/png',
                    'jpg': 'image/jpeg', 'jpeg': 'image/jpeg'}
        mime = mime_map.get(ext, 'application/octet-stream')

        supabase.storage.from_(STORAGE_BUCKET).upload(
            path=storage_path,
            file=file_bytes,
            file_options={"content-type": mime, "upsert": "true"}
        )

        url_response = supabase.storage.from_(STORAGE_BUCKET).get_public_url(storage_path)
        return url_response

    except Exception as e:
        print(f"    [sync] File upload failed for {report['report_id']}: {e}")
        return None



def _sync_reference_tables(supabase):
    """
    Pushes static reference/master tables (diseases, allergies,
    medications, and their categories) to Supabase.

    These tables have no sync_status column — they're small, static,
    seeded once locally, and safe to upsert in full every cycle. This
    MUST run before the main SYNC_TABLES loop, because patient_diseases,
    patient_allergies and patient_medications hold foreign keys into
    these tables; syncing the children first would fail on the FK
    constraint (or silently orphan data if no constraint exists).

    Returns (synced_table_count, error_count).
    """
    synced_tables = 0
    errors = 0

    for table, pk_col in REFERENCE_TABLES:
        assert_safe_identifier(table)    
        assert_safe_identifier(pk_col)  
        try:
            rows = execute_query(f"SELECT * FROM {table}", fetch=True)
            if not rows:
                continue
            supabase.table(table).upsert(rows, on_conflict=pk_col).execute()
            synced_tables += 1
        except Exception as e:
            errors += 1
            print(f"    [sync] ✗ reference table {table}: {e}")

    return synced_tables, errors



def _mark_status(table, pk_col, pk_val, status):
    """Helper: update sync_status for one row."""
    assert_safe_identifier(table)
    assert_safe_identifier(pk_col)
    execute_query(
        f"UPDATE {table} SET sync_status = ? WHERE {pk_col} = ?",
        (status, pk_val)
    )


def _recover_stale_syncing_rows():
    """
    Resets any row still marked 'syncing' back to 'pending', for every
    table in the registry.

    A row is marked 'syncing' right before its upsert is attempted, and
    is moved to 'synced' or 'error' immediately after. The only way a row
    is left sitting in 'syncing' is if the process died mid-cycle (killed,
    crashed, power loss, phone put to sleep) — a real scenario for an
    offline-first app on unreliable connections/devices. Without this
    recovery, such rows are silently skipped forever (_sync_table only
    selects 'pending'/'error') and also invisible on the dashboard
    (get_sync_status only counted 'pending'/'error').

    Safe to call at the start of every sync cycle: sync_to_cloud runs
    sequentially (no concurrent sync cycles), so any 'syncing' row found
    at the *start* of a new cycle is necessarily a leftover, not one
    currently being processed.
    """
    for table, _ in SYNC_TABLES:
        assert_safe_identifier(table)  
        try:
            execute_query(
                f"UPDATE {table} SET sync_status = 'pending' WHERE sync_status = 'syncing'"
            )
        except Exception:
            pass  


def _sync_table(supabase, table, pk_col):
    """
    Syncs all pending/error rows from one local table to Supabase.
    Returns (synced_count, error_count).
    """
    assert_safe_identifier(table)   
    assert_safe_identifier(pk_col)

    rows = execute_query(
        f"SELECT * FROM {table} WHERE sync_status IN ('pending', 'error')",
        fetch=True
    )

    if not rows:
        return 0, 0

    synced = 0
    errors = 0

    for row in rows:
        pk_val = row.get(pk_col)
        if not pk_val:
            continue

        _mark_status(table, pk_col, pk_val, 'syncing')

        try:
            payload = {k: v for k, v in row.items() if k != 'sync_status'}

            if table == 'medical_reports' and row.get('cloud_url') is None:
                cloud_url = _upload_report_file(supabase, row)
                if cloud_url:
                    payload['cloud_url'] = cloud_url
                    execute_query(
                        "UPDATE medical_reports SET cloud_url = ? WHERE report_id = ?",
                        (cloud_url, pk_val)
                    )

            supabase.table(table).upsert(payload, on_conflict=pk_col).execute()

            _mark_status(table, pk_col, pk_val, 'synced')
            synced += 1

        except Exception as e:
            _mark_status(table, pk_col, pk_val, 'error')
            errors += 1
            print(f"    [sync] ✗ {table}/{pk_val}: {e}")

    return synced, errors


def sync_to_cloud(triggered_by='system'):
    """
    Main sync function. Syncs all pending records to Supabase.
    Returns a result dict with success, message, counts, and per-table breakdown.

    Parameters:
        triggered_by — 'system' (background) or 'admin' (manual button)
    """
    if not USE_CLOUD:
        return {
            'success': False,
            'message': 'Cloud sync is not enabled. Set USE_CLOUD=True in .env',
            'synced_count': 0,
            'error_count': 0,
        }

    if not check_internet():
        return {
            'success': False,
            'message': 'No internet connection. Records will sync when connectivity returns.',
            'synced_count': 0,
            'error_count': 0,
        }

    supabase = get_supabase_client()
    if not supabase:
        return {
            'success': False,
            'message': 'Could not connect to Supabase. Check SUPABASE_URL and SUPABASE_KEY in .env',
            'synced_count': 0,
            'error_count': 0,
        }

    started_at = datetime.now()
    total_synced = 0
    total_errors = 0
    table_results = {}

    print(f"\n[sync] Starting sync ({triggered_by}) at {started_at.strftime('%H:%M:%S')}")

    _recover_stale_syncing_rows()

    ref_synced, ref_errors = _sync_reference_tables(supabase)
    if ref_errors:
        print(f"  [sync] reference tables: {ref_synced} ok, {ref_errors} failed "
              f"— dependent patient records may fail to sync until this is resolved")

    for table, pk_col in SYNC_TABLES:
        try:
            synced, errors = _sync_table(supabase, table, pk_col)
            total_synced += synced
            total_errors += errors
            if synced > 0 or errors > 0:
                table_results[table] = {'synced': synced, 'errors': errors}
                print(f"  [sync] {table}: {synced} synced, {errors} errors")
        except Exception as e:
            print(f"  [sync] {table}: FAILED — {e}")
            total_errors += 1

    duration = (datetime.now() - started_at).total_seconds()
    success = total_errors == 0

    execute_query(
        """INSERT INTO sync_logs
           (triggered_by, synced_count, error_count, duration_seconds, status, synced_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            triggered_by,
            total_synced,
            total_errors,
            round(duration, 2),
            'success' if success else 'partial' if total_synced > 0 else 'failed',
            datetime.now().isoformat()
        )
    )

    message = (
        f"Synced {total_synced} records in {duration:.1f}s"
        if success
        else f"Synced {total_synced} records, {total_errors} failed"
    )
    print(f"[sync] Done — {message}\n")

    return {
        'success': success,
        'message': message,
        'synced_count': total_synced,
        'error_count': total_errors,
        'duration_seconds': round(duration, 2),
        'table_results': table_results,
        'timestamp': datetime.now().isoformat(),
    }



def _background_sync_loop():
    """
    Runs in a daemon thread. Waits SYNC_INTERVAL_SECONDS between syncs,
    but can be woken early by request_immediate_sync() (see below) —
    e.g. right after a doctor writes a prescription — instead of always
    waiting out the full interval.
    Checks for internet before each attempt to avoid noisy error logs.
    Stops cleanly when _stop_event is set (on app shutdown).
    """
    print(f"[sync] Background sync started — interval: {SYNC_INTERVAL_SECONDS}s")

    while not _stop_event.is_set():
        _wake_event.wait(timeout=SYNC_INTERVAL_SECONDS)
        _wake_event.clear()

        if _stop_event.is_set():
            break

        if not USE_CLOUD:
            continue

        if check_internet():
            try:
                sync_to_cloud(triggered_by='background')
            except Exception as e:
                print(f"[sync] Background sync error: {e}")

    print("[sync] Background sync stopped.")


def request_immediate_sync():
    """
    Wakes the background sync thread early instead of waiting out the
    rest of its current interval. Call this after a write that patients/
    doctors would want reflected in the cloud promptly (e.g. after
    writing a prescription, adding a medical report, registering a
    patient) — see call sites in the route files.

    This is fire-and-forget and non-blocking: it just flips a flag the
    background thread is already waiting on, so it returns immediately
    and never slows down the request that triggered it. If the interval
    already has less time left than a fresh sync would take anyway, or a
    sync is currently in progress, this has no meaningful downside — the
    background thread will simply run its next cycle a little sooner.

    Safe to call even if USE_CLOUD is False or background sync hasn't
    started (the event is just a flag; nothing is listening yet).
    """
    _wake_event.set()


def start_background_sync():
    """
    Starts the background sync thread if cloud is enabled.
    Safe to call multiple times — only starts one thread.
    Called once from app/__init__.py on startup.
    """
    global _sync_thread

    if not USE_CLOUD:
        print("[sync] Cloud disabled — background sync not started.")
        return

    if _sync_thread is not None and _sync_thread.is_alive():
        print("[sync] Background sync already running.")
        return

    _stop_event.clear()
    _wake_event.clear()
    _sync_thread = threading.Thread(
        target=_background_sync_loop,
        name='meditrack-sync',
        daemon=True  
    )
    _sync_thread.start()
    print("[sync] Background sync thread started.")


def stop_background_sync():
    """
    Signals the background thread to stop.
    Called on app shutdown (optional — daemon=True handles forced kill).
    """
    _stop_event.set()



def reset_sync_status():
    """
    DEBUG ONLY — resets all rows to 'pending' for testing.
    Protected by DEBUG check in the route that calls it.
    """
    for table, _ in SYNC_TABLES:
        assert_safe_identifier(table) 
        try:
            execute_query(f"UPDATE {table} SET sync_status = 'pending'")
        except Exception:
            pass


def get_sync_logs(limit=50):
    """Returns the most recent sync log entries."""
    return execute_query(
        "SELECT * FROM sync_logs ORDER BY synced_at DESC LIMIT ?",
        (limit,),
        fetch=True
    ) or []