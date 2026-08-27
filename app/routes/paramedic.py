from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from functools import wraps
from app.database.local_db import execute_query
from app.services.auth_service import log_audit
from app.services.qr_service import validate_qr_token, refresh_emergency_snapshot
import json

paramedic_bp = Blueprint('paramedic', __name__)


def paramedic_required(f):
    """
    Decorator ensuring only logged-in paramedics access paramedic pages.
    Note: The /emergency/<token> route is PUBLIC and does NOT use this decorator.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in.', 'error')
            return redirect(url_for('auth.login'))
        if session.get('role') != 'paramedic':
            flash('Access denied. Paramedic only.', 'error')
            return redirect(url_for('auth.dashboard_redirect'))
        return f(*args, **kwargs)
    return decorated_function


@paramedic_bp.route('/paramedic/dashboard')
@paramedic_required
def dashboard():
    """
    Paramedic home page — shows a large QR scan button.
    Simple interface designed for use in emergency situations.
    """
    return render_template('paramedic/dashboard.html',
        paramedic_name=session.get('username')
    )


@paramedic_bp.route('/paramedic/scan')
@paramedic_required
def scan():
    """
    QR scanner page for paramedics.

    This didn't exist before — the dashboard's "Open Scanner" button
    linked straight to /doctor/scan, which is @doctor_required and
    correctly refused any paramedic with "Access denied. This page is
    for doctors only." Even if a paramedic got past that, the doctor
    scan page's JS redirects to /doctor/access/<token> (the doctor's
    15-minute session flow), not /emergency/<token> — the public,
    tokenless view paramedics are actually meant to land on. So the
    core paramedic workflow — scan QR, see emergency info — was broken
    end to end, not just gated.

    This page reuses the same camera/manual-entry UI as the doctor's
    scanner but redirects to /emergency/<token> instead.
    """
    return render_template('paramedic/scan.html')


@paramedic_bp.route('/emergency/<token>')
def emergency_view(token):
    """
    PUBLIC emergency page — accessible WITHOUT any login.
    This is what appears when someone scans a patient's QR code.

    Shows ONLY critical emergency information:
    - Full name and blood group
    - Life-threatening allergies (highlighted in red)
    - Active diseases
    - Current medications
    - Emergency contacts

    Does NOT show:
    - Aadhaar, phone number, address
    - Full medical history
    - Uploaded reports

    Parameters:
        token - The secure token from the patient's QR code
    """

    patient_id = validate_qr_token(token)

    if not patient_id:
        return render_template('paramedic/invalid_qr.html'), 404

    refresh_emergency_snapshot(patient_id)

    snapshot = execute_query(
        "SELECT * FROM patient_emergency_snapshot WHERE patient_id = ?",
        (patient_id,), fetchone=True
    )

    patient = execute_query(
        """SELECT patient_id, first_name, last_name, gender, date_of_birth,
                  blood_group, has_chronic_disease, has_life_threat_allergy,
                  is_pregnant, organ_donor_status
           FROM patients WHERE patient_id = ?""",
        (patient_id,), fetchone=True
    )

    if not patient:
        return render_template('paramedic/invalid_qr.html'), 404

    active_diseases = []
    life_threat_allergies = []
    current_medications = []
    emergency_contacts = []

    if snapshot:
        try:
            active_diseases = json.loads(snapshot.get('active_diseases_json', '[]'))
            life_threat_allergies = json.loads(snapshot.get('life_threat_allergies_json', '[]'))
            current_medications = json.loads(snapshot.get('current_medications_json', '[]'))
            emergency_contacts = json.loads(snapshot.get('emergency_contacts_json', '[]'))
        except Exception:
            pass

    if not active_diseases:
        active_diseases_raw = execute_query(
            """SELECT dm.disease_name, pd.severity, pd.status
               FROM patient_diseases pd
               JOIN disease_master dm ON pd.disease_id = dm.disease_id
               WHERE pd.patient_id = ? AND pd.status = 'Active' AND pd.is_emergency_relevant = 1
                 AND pd.is_deleted = 0""",
            (patient_id,), fetch=True
        )
        active_diseases = active_diseases_raw or []

    if not life_threat_allergies:
        life_threat_raw = execute_query(
            """SELECT am.allergy_name, pa.reaction_type, pa.severity
               FROM patient_allergies pa
               JOIN allergy_master am ON pa.allergy_id = am.allergy_id
               WHERE pa.patient_id = ? AND pa.is_life_threatening = 1 AND pa.is_deleted = 0""",
            (patient_id,), fetch=True
        )
        life_threat_allergies = life_threat_raw or []

    if not current_medications:
        current_meds_raw = execute_query(
            """SELECT mm.generic_name, mm.brand_name, pm.dose, pm.frequency
               FROM patient_medications pm
               JOIN medication_master mm ON pm.medication_id = mm.medication_id
               WHERE pm.patient_id = ? AND pm.is_currently_taking = 1""",
            (patient_id,), fetch=True
        )
        current_medications = current_meds_raw or []

    if not emergency_contacts:
        contacts_raw = execute_query(
            """SELECT name, relationship, phone_number
               FROM emergency_contacts
               WHERE patient_id = ?
               ORDER BY priority_order""",
            (patient_id,), fetch=True
        )
        emergency_contacts = contacts_raw or []

    execute_query(
        """INSERT INTO audit_log (audit_id, user_id, user_role, action, target_patient_id, details, ip_address, timestamp)
           VALUES (?, 'EMERGENCY_SCAN', 'public', 'EMERGENCY_QR_ACCESS', ?, ?, ?, ?)""",
        (
            __import__('uuid').uuid4().__str__(),
            patient_id,
            'Emergency QR code scanned — public access',
            request.remote_addr,
            __import__('datetime').datetime.now().isoformat()
        )
    )

    return render_template('paramedic/emergency_view.html',
        patient=patient,
        active_diseases=active_diseases,
        life_threat_allergies=life_threat_allergies,
        current_medications=current_medications,
        emergency_contacts=emergency_contacts,
        snapshot_time=snapshot.get('last_updated', 'Unknown') if snapshot else 'Unknown'
    )