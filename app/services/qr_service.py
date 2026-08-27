import hashlib
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from config import LOCAL_UPLOAD_FOLDER, SECRET_KEY, APP_BASE_URL
from app.database.local_db import execute_query

try:
    import qrcode
    from PIL import Image
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False


def generate_patient_token(patient_id):
    """
    Deterministic secure token derived from patient_id + SECRET_KEY.
    Same patient always gets the same token — safe to regenerate at any time.
    Returns a 32-character hex string.
    """
    raw = f"{patient_id}{SECRET_KEY}meditrack_qr"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def validate_qr_token(token):
    """
    Finds the patient whose qr_token matches the given token.
    Single indexed DB lookup — does NOT loop through all patients.
    Returns patient_id string or None.
    """
    result = execute_query(
        "SELECT patient_id FROM patients WHERE qr_token = ?",
        (token,),
        fetchone=True
    )
    return result['patient_id'] if result else None


def generate_qr_code(patient_id):
    """
    Generates a QR code PNG for the patient and saves it locally.
    Also stores the secure token in patients.qr_token.
    Returns dict with success, qr_path, emergency_url, qr_available.
    """
    token = generate_patient_token(patient_id)

    execute_query(
        "UPDATE patients SET qr_token = ? WHERE patient_id = ?",
        (token, patient_id)
    )

    emergency_url = f"{APP_BASE_URL}/emergency/{token}"

    qr_folder = os.path.join(LOCAL_UPLOAD_FOLDER, 'qr_codes')
    os.makedirs(qr_folder, exist_ok=True)

    qr_filename = f"qr_{patient_id[:8]}.png"
    qr_path_abs = os.path.join(qr_folder, qr_filename)
    qr_path_rel = f"uploads/qr_codes/{qr_filename}"

    if not QR_AVAILABLE:
        with open(qr_path_abs.replace('.png', '.txt'), 'w') as f:
            f.write(f"Emergency URL: {emergency_url}\n")
            f.write("Install 'qrcode[pil]' to generate QR image.\n")
        return {
            'success': True,
            'qr_path': qr_path_rel,
            'emergency_url': emergency_url,
            'qr_available': False,
        }

    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(emergency_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#1a1a2e", back_color="white")
        img.save(qr_path_abs)

        execute_query(
            "UPDATE patients SET qr_code_path = ? WHERE patient_id = ?",
            (qr_path_rel, patient_id)
        )

        return {
            'success': True,
            'qr_path': qr_path_rel,
            'emergency_url': emergency_url,
            'qr_available': True,
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def get_qr_display_data(patient_id):
    """
    Returns QR display data for the patient's QR code page.
    Uses APP_BASE_URL from config (not hardcoded localhost).
    """
    token = generate_patient_token(patient_id)
    emergency_url = f"{APP_BASE_URL}/emergency/{token}"

    patient = execute_query(
        "SELECT qr_code_path FROM patients WHERE patient_id = ?",
        (patient_id,),
        fetchone=True
    )
    qr_path = patient.get('qr_code_path') if patient else None

    return {
        'qr_path': qr_path,
        'emergency_url': emergency_url,
        'token': token,
    }


def refresh_emergency_snapshot(patient_id):
    """
    Regenerates the patient_emergency_snapshot after any change to
    diseases, allergies, medications, or emergency contacts.
    Call this from doctor.py whenever those records are updated.
    """
    allergies = execute_query(
        """SELECT am.allergy_name, pa.reaction_type, pa.severity
           FROM patient_allergies pa
           JOIN allergy_master am ON pa.allergy_id = am.allergy_id
           WHERE pa.patient_id = ? AND pa.is_life_threatening = 1 AND pa.is_deleted = 0""",
        (patient_id,), fetch=True
    )
    diseases = execute_query(
        """SELECT dm.disease_name, pd.severity, pd.status
           FROM patient_diseases pd
           JOIN disease_master dm ON pd.disease_id = dm.disease_id
           WHERE pd.patient_id = ? AND pd.status = 'Active'
             AND pd.is_emergency_relevant = 1 AND pd.is_deleted = 0""",
        (patient_id,), fetch=True
    )
    medications = execute_query(
        """SELECT mm.generic_name, mm.brand_name, pm.dose, pm.frequency
           FROM patient_medications pm
           JOIN medication_master mm ON pm.medication_id = mm.medication_id
           WHERE pm.patient_id = ? AND pm.is_currently_taking = 1""",
        (patient_id,), fetch=True
    )
    contacts = execute_query(
        """SELECT name, relationship, phone_number
           FROM emergency_contacts WHERE patient_id = ?
           ORDER BY priority_order""",
        (patient_id,), fetch=True
    )

    import json

    def to_list(rows):
        return [dict(r) for r in rows] if rows else []

    execute_query(
        """INSERT INTO patient_emergency_snapshot
           (patient_id, active_diseases_json, life_threat_allergies_json,
            current_medications_json, emergency_contacts_json, last_updated)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(patient_id) DO UPDATE SET
             active_diseases_json       = excluded.active_diseases_json,
             life_threat_allergies_json = excluded.life_threat_allergies_json,
             current_medications_json   = excluded.current_medications_json,
             emergency_contacts_json    = excluded.emergency_contacts_json,
             last_updated               = excluded.last_updated""",
        (
            patient_id,
            json.dumps(to_list(diseases)),
            json.dumps(to_list(allergies)),
            json.dumps(to_list(medications)),
            json.dumps(to_list(contacts)),
            datetime.now().isoformat(),
        )
    )