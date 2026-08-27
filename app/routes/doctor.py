from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, send_file, abort, current_app
from functools import wraps
from app.database.local_db import execute_query, assert_safe_identifier
from app.services.auth_service import log_audit, create_doctor_session, validate_doctor_session
from app.services.sync_service import get_sync_status, request_immediate_sync
from app.services.qr_service import validate_qr_token
import json
import os
import uuid
from datetime import datetime

doctor_bp = Blueprint('doctor', __name__, url_prefix='/doctor')

def doctor_required(f):
    """
    Decorator that checks the current user is a logged-in doctor.
    Redirects to login if not authenticated.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('auth.login'))
        if session.get('role') != 'doctor':
            flash('Access denied. This page is for doctors only.', 'error')
            return redirect(url_for('auth.dashboard_redirect'))
        return f(*args, **kwargs)
    return decorated_function


@doctor_bp.route('/dashboard')
@doctor_required
def dashboard():
    """
    Doctor home page showing:
    - Quick scan button (main action)
    - Today's active sessions
    - Recent activity from audit log
    - Sync status
    """
    doctor_id = session['user_id']

    today = datetime.now().date().isoformat()
    sessions_today = execute_query(
        """SELECT COUNT(*) as cnt FROM doctor_sessions
           WHERE doctor_user_id = ? AND started_at LIKE ?""",
        (doctor_id, f"{today}%"), fetchone=True
    )

    recent_prescriptions = execute_query(
        """SELECT p.*, pt.first_name, pt.last_name
           FROM prescriptions p
           JOIN patients pt ON p.patient_id = pt.patient_id
           WHERE p.doctor_user_id = ?
           ORDER BY p.prescription_date DESC LIMIT 5""",
        (doctor_id,), fetch=True
    )

    sync_info = get_sync_status()

    return render_template('doctor/dashboard.html',
        doctor_name=session.get('username'),
        sessions_today=sessions_today['cnt'] if sessions_today else 0,
        recent_prescriptions=recent_prescriptions or [],
        sync_info=sync_info
    )


@doctor_bp.route('/scan')
@doctor_required
def scan_qr():
    """
    Shows the QR code scanner interface.
    Doctor points their camera at patient's QR code.
    The browser's camera API reads the QR code.
    Then redirects to /doctor/access/<token>
    """
    return render_template('doctor/scan_qr.html')


@doctor_bp.route('/access/<token>')
@doctor_required
def access_patient(token):
    """
    Called after a QR code is scanned.
    Validates the token from the QR code.
    Creates a new 15-minute session for this doctor-patient pair.
    Then redirects to the patient view.

    Parameters:
        token - The secure token encoded in the patient's QR code
    """
    doctor_id = session['user_id']

    patient_id = validate_qr_token(token)

    if not patient_id:
        flash('Invalid or expired QR code. Please ask patient to show their QR code again.', 'error')
        return redirect(url_for('doctor.scan_qr'))

    session_info = create_doctor_session(doctor_id, patient_id)

    log_audit(
        user_id=doctor_id,
        user_role='doctor',
        action='QR_SCAN',
        target_patient_id=patient_id,
        details=f"Doctor scanned patient QR. Session expires at {session_info['expires_at']}",
        ip_address=request.remote_addr
    )

    flash(f'QR code verified! You have {session_info["minutes_remaining"]} minutes to view this patient\'s records.', 'success')
    return redirect(url_for('doctor.view_patient', patient_id=patient_id))


@doctor_bp.route('/patient/<patient_id>')
@doctor_required
def view_patient(patient_id):
    """
    Shows a patient's complete medical records to the doctor.
    ONLY accessible if there is a valid, non-expired 15-minute session.
    If session has expired, doctor must scan QR again.

    Shows:
    - Patient basic info
    - Medical history (diseases, allergies)
    - Current and past medications
    - Hospitalizations and surgeries
    - All uploaded medical reports
    - All prescriptions
    """
    doctor_id = session['user_id']

    session_status = validate_doctor_session(doctor_id, patient_id)

    if not session_status['valid']:
        flash(session_status['reason'], 'warning')
        return redirect(url_for('doctor.scan_qr'))

    patient = execute_query(
        "SELECT * FROM patients WHERE patient_id = ?",
        (patient_id,), fetchone=True
    )

    if not patient:
        flash('Patient record not found.', 'error')
        return redirect(url_for('doctor.dashboard'))

    patient_age = None
    if patient.get('date_of_birth'):
        try:
            dob = datetime.strptime(patient['date_of_birth'], '%Y-%m-%d')
            today = datetime.now()
            patient_age = today.year - dob.year - (
                (today.month, today.day) < (dob.month, dob.day)
            )
        except ValueError:
            pass  

    diseases = execute_query(
        """SELECT pd.*, dm.disease_name, dm.icd10_code, dm.risk_level, dm.is_chronic
           FROM patient_diseases pd
           JOIN disease_master dm ON pd.disease_id = dm.disease_id
           WHERE pd.patient_id = ? AND pd.is_deleted = 0
           ORDER BY pd.status, pd.diagnosed_date DESC""",
        (patient_id,), fetch=True
    )

    allergies = execute_query(
        """SELECT pa.*, am.allergy_name, ac.category_name
           FROM patient_allergies pa
           JOIN allergy_master am ON pa.allergy_id = am.allergy_id
           LEFT JOIN allergy_categories ac ON am.allergy_category_id = ac.allergy_category_id
           WHERE pa.patient_id = ? AND pa.is_deleted = 0
           ORDER BY pa.is_life_threatening DESC""",
        (patient_id,), fetch=True
    )

    medications = execute_query(
        """SELECT pm.*, mm.generic_name, mm.brand_name, mm.drug_class
           FROM patient_medications pm
           JOIN medication_master mm ON pm.medication_id = mm.medication_id
           WHERE pm.patient_id = ?
           ORDER BY pm.is_currently_taking DESC, pm.start_date DESC""",
        (patient_id,), fetch=True
    )

    hospitalizations = execute_query(
        "SELECT * FROM hospitalizations WHERE patient_id = ? AND is_deleted = 0 ORDER BY admission_date DESC",
        (patient_id,), fetch=True
    )

    surgeries = execute_query(
        "SELECT * FROM surgeries WHERE patient_id = ? AND is_deleted = 0 ORDER BY surgery_date DESC",
        (patient_id,), fetch=True
    )

    prescriptions = execute_query(
        """SELECT p.*, u.username as doctor_username
           FROM prescriptions p
           JOIN users u ON p.doctor_user_id = u.user_id
           WHERE p.patient_id = ?
           ORDER BY p.prescription_date DESC""",
        (patient_id,), fetch=True
    )

    for prescription in (prescriptions or []):
        try:
            prescription['medications_list'] = json.loads(prescription.get('medications_json', '[]'))
        except Exception:
            prescription['medications_list'] = []

    reports = execute_query(
        "SELECT * FROM medical_reports WHERE patient_id = ? ORDER BY upload_date DESC",
        (patient_id,), fetch=True
    )

    log_audit(
        user_id=doctor_id,
        user_role='doctor',
        action='VIEW_PATIENT_RECORD',
        target_patient_id=patient_id,
        details=f"Doctor viewed full patient record. Session valid for {session_status['minutes_remaining']}m {session_status['seconds_remaining']}s",
        ip_address=request.remote_addr
    )

    return render_template('doctor/patient_view.html',
        patient=patient,
        patient_age=patient_age,
        diseases=diseases or [],
        allergies=allergies or [],
        medications=medications or [],
        hospitalizations=hospitalizations or [],
        surgeries=surgeries or [],
        prescriptions=prescriptions or [],
        reports=reports or [],
        session_status=session_status,
        doctor_name=session.get('username')
    )


@doctor_bp.route('/session-status/<patient_id>')
@doctor_required
def check_session_status(patient_id):
    """
    API endpoint called by the browser every 30 seconds to check session time.
    Returns JSON with remaining time so the countdown timer updates.

    Parameters:
        patient_id - The patient being viewed
    Returns:
        JSON with valid, minutes_remaining, seconds_remaining
    """
    doctor_id = session['user_id']
    status = validate_doctor_session(doctor_id, patient_id)
    return jsonify(status)


@doctor_bp.route('/prescribe/<patient_id>', methods=['GET', 'POST'])
@doctor_required
def write_prescription(patient_id):
    """
    GET:  Shows prescription form
    POST: Saves new prescription to database

    Only accessible during an active 15-minute session.
    """
    doctor_id = session['user_id']

    session_status = validate_doctor_session(doctor_id, patient_id)
    if not session_status['valid']:
        flash(session_status['reason'], 'warning')
        return redirect(url_for('doctor.scan_qr'))

    patient = execute_query(
        "SELECT * FROM patients WHERE patient_id = ?",
        (patient_id,), fetchone=True
    )

    if request.method == 'POST':
        diagnosis = request.form.get('diagnosis', '').strip()
        instructions = request.form.get('instructions', '').strip()
        follow_up_date = request.form.get('follow_up_date', '')

        med_names = request.form.getlist('med_name[]')
        med_doses = request.form.getlist('med_dose[]')
        med_freq = request.form.getlist('med_frequency[]')

        medications_list = []
        for name, dose, freq in zip(med_names, med_doses, med_freq):
            if name.strip():
                medications_list.append({
                    'name': name.strip(),
                    'dose': dose.strip(),
                    'frequency': freq.strip()
                })

        prescription_id = str(uuid.uuid4())
        execute_query(
            """INSERT INTO prescriptions
               (prescription_id, patient_id, doctor_user_id, prescription_date,
                diagnosis, medications_json, instructions, follow_up_date, sync_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (prescription_id, patient_id, doctor_id,
             datetime.now().strftime('%Y-%m-%d'),
             diagnosis, json.dumps(medications_list), instructions, follow_up_date)
        )

        log_audit(doctor_id, 'doctor', 'WRITE_PRESCRIPTION',
                  target_patient_id=patient_id,
                  details=f'Prescription written: {diagnosis}',
                  ip_address=request.remote_addr)

        request_immediate_sync()

        flash('Prescription saved successfully!', 'success')
        return redirect(url_for('doctor.view_patient', patient_id=patient_id))

    return render_template('doctor/prescribe.html',
        patient=patient,
        session_status=session_status
    )


REPORT_MIME_TYPES = {
    'pdf':  'application/pdf',
    'png':  'image/png',
    'jpg':  'image/jpeg',
    'jpeg': 'image/jpeg',
}


@doctor_bp.route('/report/<report_id>/view')
@doctor_required
def view_report(report_id):
    """
    Streams a patient's uploaded medical report so the doctor can view it
    in the browser — never as a downloadable attachment.

    Access requires the same valid, non-expired 15-minute session used for
    /doctor/patient/<id>. report_id is only ever used to look up a row —
    the actual file path on disk is the one written by the patient's
    upload handler, never taken from the request — so there's no path
    traversal surface here.

    The response is sent with Content-Disposition: inline (Flask's
    send_file default when as_attachment=False) so browsers render PDFs/
    images directly instead of prompting a save dialog, and the UI never
    exposes a separate download link. This is view-only by convention,
    not hardened DRM — a browser's own PDF viewer may still offer its own
    save/print icons — but it matches how the rest of MediTrack treats
    read-only clinical access.
    """
    doctor_id = session['user_id']

    report = execute_query(
        "SELECT * FROM medical_reports WHERE report_id = ?",
        (report_id,), fetchone=True
    )
    if not report:
        abort(404)

    patient_id = report['patient_id']

    session_status = validate_doctor_session(doctor_id, patient_id)
    if not session_status['valid']:
        flash(session_status['reason'], 'warning')
        return redirect(url_for('doctor.scan_qr'))

    local_path = os.path.join(current_app.static_folder, report['file_path'])

    if not os.path.exists(local_path):
        if report.get('cloud_url'):
            log_audit(
                user_id=doctor_id, user_role='doctor', action='VIEW_REPORT',
                target_patient_id=patient_id,
                details=f"Doctor viewed report (cloud): {report['file_name']}",
                ip_address=request.remote_addr
            )
            return redirect(report['cloud_url'])
        flash('This report file could not be found.', 'error')
        return redirect(url_for('doctor.view_patient', patient_id=patient_id))

    log_audit(
        user_id=doctor_id, user_role='doctor', action='VIEW_REPORT',
        target_patient_id=patient_id,
        details=f"Doctor viewed report: {report['file_name']}",
        ip_address=request.remote_addr
    )

    mimetype = REPORT_MIME_TYPES.get(report['file_type'].lower(), 'application/octet-stream')

    return send_file(
        local_path,
        mimetype=mimetype,
        as_attachment=False,
        download_name=report['file_name'],
        conditional=True,
    )


VERIFIABLE_RECORD_TYPES = {
    'condition':       ('patient_diseases',  'patient_disease_id'),
    'allergy':         ('patient_allergies', 'patient_allergy_id'),
    'hospitalization': ('hospitalizations',  'hospitalization_id'),
    'surgery':         ('surgeries',         'surgery_id'),
    'report':          ('medical_reports',   'report_id'),
}


@doctor_bp.route('/verify/<record_type>/<record_id>', methods=['POST'])
@doctor_required
def verify_record(record_type, record_id):
    """
    Doctor marks a patient-entered record as clinically verified.

    This converts recorded_by from 'patient' to 'clinical' — the exact
    flag that already drives the "Patient Reported – Not Verified" badge
    everywhere it's shown (both doctor and patient views). Once verified,
    the record is indistinguishable from one a clinician entered directly
    — there's no separate "verified" state layered on top, matching how
    this was scoped.

    Requires an active 15-minute session for the record's patient, same
    as writing a prescription — verification only happens in the context
    of an actual clinical visit, not as a standalone admin action.
    """
    config = VERIFIABLE_RECORD_TYPES.get(record_type)
    if not config:
        abort(404)
    table, pk_col = config
    assert_safe_identifier(table)
    assert_safe_identifier(pk_col)

    doctor_id = session['user_id']

    record = execute_query(
        f"SELECT patient_id, recorded_by FROM {table} WHERE {pk_col} = ?",
        (record_id,), fetchone=True
    )
    if not record:
        abort(404)

    patient_id = record['patient_id']

    session_status = validate_doctor_session(doctor_id, patient_id)
    if not session_status['valid']:
        flash(session_status['reason'], 'warning')
        return redirect(url_for('doctor.scan_qr'))

    if record['recorded_by'] != 'patient':
        flash('This record is already clinically recorded.', 'info')
        return redirect(url_for('doctor.view_patient', patient_id=patient_id))

    if table == 'patient_allergies':
        execute_query(
            f"UPDATE {table} SET recorded_by = 'clinical', verified_by_doctor = 1, "
            f"sync_status = 'pending' WHERE {pk_col} = ?",
            (record_id,)
        )
    else:
        execute_query(
            f"UPDATE {table} SET recorded_by = 'clinical', sync_status = 'pending' "
            f"WHERE {pk_col} = ?",
            (record_id,)
        )

    log_audit(doctor_id, 'doctor', 'VERIFY_RECORD',
              target_patient_id=patient_id,
              details=f'Doctor clinically verified patient-reported {record_type}: {record_id}',
              ip_address=request.remote_addr)

    request_immediate_sync()

    flash(f'{record_type.capitalize()} verified and marked as clinically recorded.', 'success')
    return redirect(url_for('doctor.view_patient', patient_id=patient_id))