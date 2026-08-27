import sqlite3
import os
import sys
import re
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from config import LOCAL_DB_PATH


def get_connection():
    """
    Creates and returns a connection to the local SQLite database.
    Uses row_factory so results come back as dictionaries (easier to use).
    Returns: sqlite3.Connection object
    """
    conn = sqlite3.connect(LOCAL_DB_PATH)
    conn.row_factory = sqlite3.Row  
    conn.execute("PRAGMA foreign_keys = ON")  
    conn.execute("PRAGMA journal_mode = WAL")  
    return conn


def init_db():
    """
    Initialises the entire database by creating all tables.
    Safe to call multiple times — uses IF NOT EXISTS.
    Call this once when the app starts.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,           -- Unique UUID for every user
            username TEXT UNIQUE NOT NULL,      -- Login username
            password_hash TEXT NOT NULL,        -- Hashed password (never plain text)
            role TEXT NOT NULL,                 -- 'patient', 'doctor', 'admin', 'paramedic'
            is_active INTEGER DEFAULT 1,        -- 1 = active, 0 = deactivated
            created_at TEXT NOT NULL,           -- When account was created
            last_login TEXT,                    -- Last login timestamp
            sync_status TEXT DEFAULT 'pending', -- Cloud sync status (was missing here —
                                                 -- caused "no such column: sync_status" errors)
            failed_login_attempts INTEGER DEFAULT 0,  -- Brute-force protection: wrong-password streak
            locked_until TEXT                          -- Brute-force protection: ISO timestamp the
                                                         -- account is locked until; NULL = not locked
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            patient_id TEXT PRIMARY KEY,        -- UUID, unique identifier for patient
            user_id TEXT NOT NULL,              -- Links to users table for login
            abha_id TEXT,                       -- ABHA health ID (nullable)
            first_name TEXT NOT NULL,           -- Patient first name
            last_name TEXT NOT NULL,            -- Patient last name
            gender TEXT NOT NULL,               -- Male / Female / Other
            date_of_birth TEXT NOT NULL,        -- Date of birth (YYYY-MM-DD)
            blood_group TEXT,                   -- A+, B+, O+, AB+, etc.
            phone_number_encrypted TEXT,        -- Phone number (encrypted for security)
            aadhaar_hash TEXT,                  -- Aadhaar stored as hash only (never raw)
            village_name TEXT,                  -- Patient's village
            district TEXT,                      -- Patient's district
            state TEXT,                         -- Patient's state
            has_chronic_disease INTEGER DEFAULT 0,   -- 1 = yes, 0 = no (emergency flag)
            has_life_threat_allergy INTEGER DEFAULT 0, -- 1 = yes, 0 = no (emergency flag)
            is_pregnant INTEGER DEFAULT 0,      -- 1 = yes, 0 = no (emergency flag)
            organ_donor_status TEXT DEFAULT 'No', -- Yes / No / Unknown
            qr_code_path TEXT,                  -- Path to generated QR code image
            created_at TEXT NOT NULL,           -- When record was created
            updated_at TEXT,                    -- When record was last updated
            sync_status TEXT DEFAULT 'pending', -- 'synced' or 'pending' (for cloud sync)
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_patients_blood_group ON patients(blood_group)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_patients_district ON patients(district)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_patients_village ON patients(village_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_patients_dob ON patients(date_of_birth)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS disease_master (
            disease_id TEXT PRIMARY KEY,        -- Unique disease ID
            icd10_code TEXT,                    -- International disease code (e.g. J45 = Asthma)
            disease_category_id TEXT,           -- Links to disease_categories
            disease_name TEXT NOT NULL,         -- English name
            localized_name_hindi TEXT,          -- Hindi name for local use
            risk_level TEXT DEFAULT 'Low',      -- Low / Medium / High / Critical
            is_chronic INTEGER DEFAULT 0        -- 1 = chronic disease, 0 = acute
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_disease_icd10 ON disease_master(icd10_code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_disease_chronic ON disease_master(is_chronic)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS disease_categories (
            disease_category_id TEXT PRIMARY KEY,  -- Unique category ID
            category_name TEXT NOT NULL,            -- e.g. Respiratory, Cardiovascular
            icon_code TEXT,                         -- Icon identifier for UI
            priority_weight INTEGER DEFAULT 1       -- Higher = more critical category
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patient_diseases (
            patient_disease_id TEXT PRIMARY KEY,    -- Unique record ID
            patient_id TEXT NOT NULL,               -- Links to patients table
            disease_id TEXT NOT NULL,               -- Links to disease_master
            diagnosed_date TEXT,                    -- When diagnosed (YYYY-MM-DD)
            status TEXT DEFAULT 'Active',           -- Active / Controlled / Recovered
            severity TEXT DEFAULT 'Mild',           -- Mild / Moderate / Severe
            is_emergency_relevant INTEGER DEFAULT 0, -- 1 = show in emergency view
            last_checkup_date TEXT,                 -- Last checkup date
            notes TEXT,                             -- Doctor notes
            sync_status TEXT DEFAULT 'pending',     -- Cloud sync status
            recorded_by TEXT DEFAULT 'clinical',    -- 'clinical' (doctor/seed) or 'patient' (self-reported)
            is_deleted INTEGER DEFAULT 0,           -- Soft delete: sync engine only upserts, never
                                                     -- issues real DELETEs, so "deleting" a patient-
                                                     -- entered record just flips this flag — it then
                                                     -- flows through the EXISTING sync path unchanged.
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
            FOREIGN KEY (disease_id) REFERENCES disease_master(disease_id)
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_patient_diseases_pid ON patient_diseases(patient_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_patient_diseases_status ON patient_diseases(patient_id, status)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS allergy_categories (
            allergy_category_id TEXT PRIMARY KEY,   -- Unique category ID
            category_name TEXT NOT NULL             -- e.g. Drug, Food, Environmental
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS allergy_master (
            allergy_id TEXT PRIMARY KEY,            -- Unique allergy ID
            allergy_name TEXT NOT NULL,             -- Name of allergy (e.g. Penicillin)
            allergy_category_id TEXT,               -- Links to allergy_categories
            FOREIGN KEY (allergy_category_id) REFERENCES allergy_categories(allergy_category_id)
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_allergy_category ON allergy_master(allergy_category_id)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patient_allergies (
            patient_allergy_id TEXT PRIMARY KEY,    -- Unique record ID
            patient_id TEXT NOT NULL,               -- Links to patients
            allergy_id TEXT NOT NULL,               -- Links to allergy_master
            reaction_type TEXT,                     -- e.g. Rash, Anaphylaxis, Swelling
            severity TEXT DEFAULT 'Mild',           -- Mild / Moderate / Severe / Life-threatening
            is_life_threatening INTEGER DEFAULT 0,  -- 1 = life threatening (CRITICAL FLAG)
            verified_by_doctor INTEGER DEFAULT 0,   -- 1 = doctor confirmed, 0 = self-reported
            created_at TEXT NOT NULL,               -- When recorded
            sync_status TEXT DEFAULT 'pending',     -- Cloud sync status
            notes TEXT,                             -- Free-text detail (e.g. reaction description)
            recorded_by TEXT DEFAULT 'clinical',    -- 'clinical' (doctor/seed) or 'patient' (self-reported)
            is_deleted INTEGER DEFAULT 0,           -- Soft delete — see patient_diseases comment above
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
            FOREIGN KEY (allergy_id) REFERENCES allergy_master(allergy_id)
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_patient_allergies_pid ON patient_allergies(patient_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_patient_allergies_lifethreat ON patient_allergies(patient_id, is_life_threatening)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS medication_master (
            medication_id TEXT PRIMARY KEY,         -- Unique medication ID
            generic_name TEXT NOT NULL,             -- Generic drug name (e.g. Amoxicillin)
            brand_name TEXT,                        -- Brand name (e.g. Amoxil)
            drug_class TEXT,                        -- Drug class (e.g. Penicillin Antibiotic)
            contraindications_json TEXT             -- JSON list of contraindications
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_medication_generic ON medication_master(generic_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_medication_class ON medication_master(drug_class)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patient_medications (
            patient_medication_id TEXT PRIMARY KEY, -- Unique record ID
            patient_id TEXT NOT NULL,               -- Links to patients
            medication_id TEXT NOT NULL,            -- Links to medication_master
            is_currently_taking INTEGER DEFAULT 1,  -- 1 = current, 0 = past medication
            start_date TEXT,                        -- When medication started
            end_date TEXT,                          -- When medication ended (null if ongoing)
            dose TEXT,                              -- Dosage (e.g. 500mg)
            frequency TEXT,                         -- How often (e.g. Twice daily)
            prescribed_by TEXT,                     -- Doctor who prescribed
            notes TEXT,                             -- Additional notes
            sync_status TEXT DEFAULT 'pending',     -- Cloud sync status
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
            FOREIGN KEY (medication_id) REFERENCES medication_master(medication_id)
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_patient_meds_pid ON patient_medications(patient_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_patient_meds_current ON patient_medications(patient_id, is_currently_taking)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hospitalizations (
            hospitalization_id TEXT PRIMARY KEY,    -- Unique record ID
            patient_id TEXT NOT NULL,               -- Links to patients
            admission_date TEXT NOT NULL,           -- Date admitted
            discharge_date TEXT,                    -- Date discharged (null if still admitted)
            reason TEXT,                            -- Reason for admission
            hospital_name TEXT,                     -- Name of hospital
            district TEXT,                          -- District of hospital
            notes TEXT,                             -- Additional notes
            sync_status TEXT DEFAULT 'pending',     -- Cloud sync status
            recorded_by TEXT DEFAULT 'clinical',    -- 'clinical' (doctor/seed) or 'patient' (self-reported)
            is_deleted INTEGER DEFAULT 0,           -- Soft delete — see patient_diseases comment above
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_hosp_patient ON hospitalizations(patient_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_hosp_date ON hospitalizations(admission_date)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS surgeries (
            surgery_id TEXT PRIMARY KEY,            -- Unique record ID
            patient_id TEXT NOT NULL,               -- Links to patients
            procedure_name TEXT NOT NULL,           -- Name of surgery
            procedure_code TEXT,                    -- Medical procedure code
            surgery_date TEXT NOT NULL,             -- Date of surgery
            complications TEXT,                     -- Any complications noted
            hospital_name TEXT,                     -- Where surgery was performed
            surgeon_name TEXT,                      -- Surgeon's name
            sync_status TEXT DEFAULT 'pending',     -- Cloud sync status
            recorded_by TEXT DEFAULT 'clinical',    -- 'clinical' (doctor/seed) or 'patient' (self-reported)
            is_deleted INTEGER DEFAULT 0,           -- Soft delete — see patient_diseases comment above
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_surgery_patient ON surgeries(patient_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_surgery_date ON surgeries(surgery_date)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patient_emergency_snapshot (
            patient_id TEXT PRIMARY KEY,            -- Links to patients (one snapshot per patient)
            blood_group TEXT,                       -- Blood group for emergency
            active_diseases_json TEXT,              -- JSON of active diseases
            life_threat_allergies_json TEXT,        -- JSON of life-threatening allergies
            current_medications_json TEXT,          -- JSON of current medications
            emergency_contacts_json TEXT,           -- JSON of emergency contacts
            last_updated TEXT,                      -- When snapshot was last refreshed
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emergency_contacts (
            contact_id TEXT PRIMARY KEY,            -- Unique contact ID
            patient_id TEXT NOT NULL,               -- Links to patients
            name TEXT NOT NULL,                     -- Contact's full name
            relationship TEXT NOT NULL,             -- e.g. Father, Mother, Spouse
            phone_number TEXT NOT NULL,             -- Contact's phone number
            priority_order INTEGER DEFAULT 1,       -- 1 = call first, 2 = call second
            sync_status TEXT DEFAULT 'pending',     -- Cloud sync status
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_emergency_contacts_patient ON emergency_contacts(patient_id)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS medical_reports (
            report_id TEXT PRIMARY KEY,             -- Unique report ID
            patient_id TEXT NOT NULL,               -- Links to patients
            file_name TEXT NOT NULL,                -- Original file name
            file_path TEXT NOT NULL,                -- Local storage path
            file_type TEXT NOT NULL,                -- pdf / png / jpg / jpeg
            upload_date TEXT NOT NULL,              -- When uploaded
            description TEXT,                       -- Patient's description of report
            cloud_url TEXT,                         -- Supabase URL after sync
            sync_status TEXT DEFAULT 'pending',     -- Cloud sync status
            recorded_by TEXT DEFAULT 'patient',     -- 'patient' (self-uploaded) or 'clinical'
                                                     -- (doctor-verified) — same convention as
                                                     -- patient_diseases/patient_allergies/etc.
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reports_patient ON medical_reports(patient_id)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctor_sessions (
            session_id TEXT PRIMARY KEY,            -- Unique session ID
            doctor_user_id TEXT NOT NULL,           -- Which doctor scanned
            patient_id TEXT NOT NULL,               -- Which patient's QR was scanned
            started_at TEXT NOT NULL,               -- When session started
            expires_at TEXT NOT NULL,               -- When session expires (started + 15 min)
            is_active INTEGER DEFAULT 1,            -- 1 = active, 0 = expired
            FOREIGN KEY (doctor_user_id) REFERENCES users(user_id),
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            audit_id TEXT PRIMARY KEY,              -- Unique audit entry ID
            user_id TEXT NOT NULL,                  -- Who performed the action
            user_role TEXT NOT NULL,                -- Their role at time of action
            action TEXT NOT NULL,                   -- What action was performed
            target_patient_id TEXT,                 -- Which patient was accessed (if any)
            details TEXT,                           -- Additional details
            ip_address TEXT,                        -- IP address of request
            timestamp TEXT NOT NULL,                -- When it happened
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_patient ON audit_log(target_patient_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prescriptions (
            prescription_id TEXT PRIMARY KEY,       -- Unique prescription ID
            patient_id TEXT NOT NULL,               -- Links to patients
            doctor_user_id TEXT NOT NULL,           -- Doctor who wrote it
            prescription_date TEXT NOT NULL,        -- Date of prescription
            diagnosis TEXT,                         -- What was diagnosed
            medications_json TEXT,                  -- JSON list of prescribed medications
            instructions TEXT,                      -- Doctor's instructions
            follow_up_date TEXT,                    -- Next appointment date
            sync_status TEXT DEFAULT 'pending',     -- Cloud sync status
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
            FOREIGN KEY (doctor_user_id) REFERENCES users(user_id)
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prescriptions_patient ON prescriptions(patient_id)")

    conn.commit()
    conn.close()
    print("✅ Database initialised successfully with all tables.")


_SQL_IDENTIFIER_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def assert_safe_identifier(name):
    """
    Defense-in-depth guard for the handful of places in this codebase
    that build a TABLE or COLUMN name into a query string (sync_service.py's
    per-table sync loop, and patient.py's generic history add/edit/delete
    routes). This is necessary because SQLite's parameterized queries
    (the `?` placeholders used everywhere else) only bind VALUES — SQL
    doesn't support parameterizing identifiers like table/column names,
    so building those into the string is unavoidable wherever the table
    itself varies.

    Security audit note: every current call site already only ever
    passes a name pulled from a hardcoded Python list/dict defined in
    source code (SYNC_TABLES, REFERENCE_TABLES, HISTORY_RECORD_TYPES) —
    never from request.form/args or any other user input. So this isn't
    patching an existing vulnerability. It's a safety net: if a future
    change ever accidentally routes user input into one of these spots,
    this makes it fail loudly and immediately (ValueError) instead of
    silently becoming a SQL injection hole. Table/column names are
    plain identifiers (letters, digits, underscore, not starting with a
    digit) — this pattern is intentionally strict.
    """
    if not isinstance(name, str) or not _SQL_IDENTIFIER_PATTERN.match(name):
        raise ValueError(f"Unsafe SQL identifier rejected: {name!r}")
    return name


def execute_query(query, params=(), fetch=False, fetchone=False):
    """
    Executes a SQL query on the local database.
    Parameters:
        query    - The SQL query string
        params   - Tuple of parameters to safely inject into query
        fetch    - If True, returns all matching rows
        fetchone - If True, returns only the first matching row
    Returns: rows if fetch/fetchone, else None
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        if fetchone:
            result = cursor.fetchone()
            return dict(result) if result else None
        if fetch:
            results = cursor.fetchall()
            return [dict(row) for row in results]
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def add_missing_columns():
    """
    Adds columns introduced after initial schema creation.
    Safe to call on every startup — uses ALTER TABLE ... IF NOT EXISTS pattern
    by catching the 'duplicate column' error silently.
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("ALTER TABLE patients ADD COLUMN qr_token TEXT")
        
        conn.commit()
        print("  Added qr_token column to patients")
    except Exception:
        pass  

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN sync_status TEXT DEFAULT 'pending'")
        conn.commit()
        print("  Added sync_status column to users")
    except Exception:
        pass  

    for column_def in ["failed_login_attempts INTEGER DEFAULT 0", "locked_until TEXT"]:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {column_def}")
            conn.commit()
        except Exception:
            pass 

    try:
        cursor.execute(
            """INSERT OR IGNORE INTO users
               (user_id, username, password_hash, role, is_active, created_at, sync_status)
               VALUES ('EMERGENCY_SCAN', '__system_emergency_scan__', 'no-login:disabled',
                       'system', 0, ?, 'pending')""",
            (datetime.now().isoformat(),)
        )
        conn.commit()
    except Exception:
        pass  

    _history_migrations = [
        ("patient_diseases", "recorded_by TEXT DEFAULT 'clinical'"),
        ("patient_diseases", "is_deleted INTEGER DEFAULT 0"),
        ("patient_allergies", "notes TEXT"),
        ("patient_allergies", "recorded_by TEXT DEFAULT 'clinical'"),
        ("patient_allergies", "is_deleted INTEGER DEFAULT 0"),
        ("hospitalizations", "recorded_by TEXT DEFAULT 'clinical'"),
        ("hospitalizations", "is_deleted INTEGER DEFAULT 0"),
        ("surgeries", "recorded_by TEXT DEFAULT 'clinical'"),
        ("surgeries", "is_deleted INTEGER DEFAULT 0"),
        ("medical_reports", "recorded_by TEXT DEFAULT 'patient'"),
    ]
    for table, column_def in _history_migrations:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
            conn.commit()
        except Exception:
            pass 

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sync_logs (
            log_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            triggered_by  TEXT NOT NULL DEFAULT 'system',
            synced_count  INTEGER DEFAULT 0,
            error_count   INTEGER DEFAULT 0,
            duration_seconds REAL DEFAULT 0,
            status        TEXT NOT NULL,   -- 'success' | 'partial' | 'failed'
            synced_at     TEXT NOT NULL
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_sync_logs_time ON sync_logs(synced_at)"
    )

    conn.commit()
    conn.close()