from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from functools import wraps
from app.database.local_db import execute_query, assert_safe_identifier
from app.services.auth_service import log_audit
from app.services.sync_service import get_sync_status, request_immediate_sync
import os
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename

patient_bp = Blueprint('patient', __name__, url_prefix='/patient')


def patient_required(f):
    """
    Decorator that checks if the current user is a logged-in patient.
    If not, redirects to login page.
    Apply this to any route that only patients should access.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('auth.login'))
        if session.get('role') != 'patient':
            flash('Access denied. This page is for patients only.', 'error')
            return redirect(url_for('auth.dashboard_redirect'))
        return f(*args, **kwargs)
    return decorated_function


def get_current_patient():
    """
    Helper function to get the patient record for the currently logged-in user.
    Returns the patient dictionary or None if not found.
    """
    return execute_query(
        "SELECT * FROM patients WHERE user_id = ?",
        (session['user_id'],),
        fetchone=True
    )



@patient_bp.route('/dashboard')
@patient_required
def dashboard():
    """
    Patient home page — shows a summary of:
    - Personal info
    - Recent prescriptions
    - Active diseases
    - Current medications
    - Quick links to all features
    """
    patient = get_current_patient()
    if not patient:
        flash('Patient record not found. Please contact admin.', 'error')
        return redirect(url_for('auth.logout'))

    patient_id = patient['patient_id']

    active_diseases = execute_query(
        "SELECT COUNT(*) as cnt FROM patient_diseases WHERE patient_id = ? AND status = 'Active' AND is_deleted = 0",
        (patient_id,), fetchone=True
    )

    current_meds = execute_query(
        "SELECT COUNT(*) as cnt FROM patient_medications WHERE patient_id = ? AND is_currently_taking = 1",
        (patient_id,), fetchone=True
    )

    recent_prescription = execute_query(
        "SELECT * FROM prescriptions WHERE patient_id = ? ORDER BY prescription_date DESC LIMIT 1",
        (patient_id,), fetchone=True
    )

    reports_count = execute_query(
        "SELECT COUNT(*) as cnt FROM medical_reports WHERE patient_id = ?",
        (patient_id,), fetchone=True
    )

    sync_info = get_sync_status()

    return render_template('patient/dashboard.html',
        patient=patient,
        active_diseases_count=active_diseases['cnt'] if active_diseases else 0,
        current_meds_count=current_meds['cnt'] if current_meds else 0,
        recent_prescription=recent_prescription,
        reports_count=reports_count['cnt'] if reports_count else 0,
        sync_info=sync_info
    )


@patient_bp.route('/history')
@patient_required
def history():
    """
    Shows the patient's complete medical history including:
    - All diagnosed diseases (past and present)
    - All allergies
    - Hospitalization records
    - Surgery records

    Soft-deleted records (is_deleted = 1) are excluded — see the
    HISTORY_RECORD_TYPES / delete_history_record() comments below for why
    deletes are soft rather than real SQL DELETEs.
    """
    patient = get_current_patient()
    patient_id = patient['patient_id']

    diseases = execute_query(
        """SELECT pd.*, dm.disease_name, dm.icd10_code, dm.risk_level, dm.is_chronic
           FROM patient_diseases pd
           JOIN disease_master dm ON pd.disease_id = dm.disease_id
           WHERE pd.patient_id = ? AND pd.is_deleted = 0
           ORDER BY pd.diagnosed_date DESC""",
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

    hospitalizations = execute_query(
        "SELECT * FROM hospitalizations WHERE patient_id = ? AND is_deleted = 0 ORDER BY admission_date DESC",
        (patient_id,), fetch=True
    )

    surgeries = execute_query(
        "SELECT * FROM surgeries WHERE patient_id = ? AND is_deleted = 0 ORDER BY surgery_date DESC",
        (patient_id,), fetch=True
    )

    log_audit(session['user_id'], 'patient', 'VIEW_HISTORY',
              target_patient_id=patient_id,
              details='Patient viewed own medical history',
              ip_address=request.remote_addr)

    return render_template('patient/history.html',
        patient=patient,
        diseases=diseases or [],
        allergies=allergies or [],
        hospitalizations=hospitalizations or [],
        surgeries=surgeries or []
    )

HISTORY_RECORD_TYPES = {
    'condition': {
        'table': 'patient_diseases',
        'pk': 'patient_disease_id',
        'label': 'Condition',
        'master_table': 'disease_master',
        'master_pk': 'disease_id',
        'master_name_col': 'disease_name',
        'fk_field': 'disease_id',
        'fk_label': 'Condition',
        'has_created_at': False,
        'fields': [
            {'name': 'diagnosed_date', 'label': 'Diagnosed Date', 'type': 'date', 'required': False},
            {'name': 'status', 'label': 'Status', 'type': 'select',
             'options': ['Active', 'Controlled', 'Recovered'], 'default': 'Active'},
            {'name': 'severity', 'label': 'Severity', 'type': 'select',
             'options': ['Mild', 'Moderate', 'Severe'], 'default': 'Mild'},
            {'name': 'is_emergency_relevant', 'label': 'Show this in the emergency/QR view', 'type': 'checkbox'},
            {'name': 'notes', 'label': 'Notes', 'type': 'textarea', 'required': False},
        ],
    },
    'allergy': {
        'table': 'patient_allergies',
        'pk': 'patient_allergy_id',
        'label': 'Allergy',
        'master_table': 'allergy_master',
        'master_pk': 'allergy_id',
        'master_name_col': 'allergy_name',
        'fk_field': 'allergy_id',
        'fk_label': 'Allergy',
        'has_created_at': True,
        'fields': [
            {'name': 'reaction_type', 'label': 'Reaction Type', 'type': 'text', 'required': False},
            {'name': 'severity', 'label': 'Severity', 'type': 'select',
             'options': ['Mild', 'Moderate', 'Severe', 'Life-threatening'], 'default': 'Mild'},
            {'name': 'is_life_threatening', 'label': 'This is life-threatening', 'type': 'checkbox'},
            {'name': 'notes', 'label': 'Notes', 'type': 'textarea', 'required': False},
        ],
    },
    'hospitalization': {
        'table': 'hospitalizations',
        'pk': 'hospitalization_id',
        'label': 'Hospitalization',
        'master_table': None,
        'has_created_at': False,
        'fields': [
            {'name': 'admission_date', 'label': 'Admission Date', 'type': 'date', 'required': True},
            {'name': 'discharge_date', 'label': 'Discharge Date', 'type': 'date', 'required': False},
            {'name': 'reason', 'label': 'Reason', 'type': 'text', 'required': False},
            {'name': 'hospital_name', 'label': 'Hospital Name', 'type': 'text', 'required': False},
            {'name': 'district', 'label': 'District', 'type': 'text', 'required': False},
            {'name': 'notes', 'label': 'Notes', 'type': 'textarea', 'required': False},
        ],
    },
    'surgery': {
        'table': 'surgeries',
        'pk': 'surgery_id',
        'label': 'Surgery',
        'master_table': None,
        'has_created_at': False,
        'fields': [
            {'name': 'procedure_name', 'label': 'Procedure Name', 'type': 'text', 'required': True},
            {'name': 'procedure_code', 'label': 'Procedure Code', 'type': 'text', 'required': False},
            {'name': 'surgery_date', 'label': 'Surgery Date', 'type': 'date', 'required': True},
            {'name': 'hospital_name', 'label': 'Hospital Name', 'type': 'text', 'required': False},
            {'name': 'surgeon_name', 'label': 'Surgeon Name', 'type': 'text', 'required': False},
            {'name': 'complications', 'label': 'Complications / Notes', 'type': 'textarea', 'required': False},
        ],
    },
}


def _validate_history_config(config):
    """
    Defense-in-depth guard: validates every table/column identifier in a
    HISTORY_RECORD_TYPES entry before it's used to build a query.

    config only ever comes from the hardcoded HISTORY_RECORD_TYPES dict
    above — record_type is looked up via .get() and the request is
    rejected if it's not one of the known keys, so none of these values
    can be influenced by the request today. This exists so a future edit
    to HISTORY_RECORD_TYPES (or a refactor that starts building config
    dynamically) can't silently open a SQL injection hole. See
    assert_safe_identifier()'s docstring in local_db.py for the full
    reasoning.
    """
    assert_safe_identifier(config['table'])
    assert_safe_identifier(config['pk'])
    if config.get('master_table'):
        assert_safe_identifier(config['master_table'])
        assert_safe_identifier(config['master_pk'])
        assert_safe_identifier(config['master_name_col'])
        assert_safe_identifier(config['fk_field'])
    for field in config['fields']:
        assert_safe_identifier(field['name'])


def _get_master_options(config):
    """Fetch dropdown options from the master table, if this record type uses one."""
    if not config.get('master_table'):
        return None
    return execute_query(
        f"SELECT {config['master_pk']} as id, {config['master_name_col']} as name "
        f"FROM {config['master_table']} ORDER BY {config['master_name_col']}",
        fetch=True
    )


def _collect_form_values(config):
    """
    Reads this record type's fields from the submitted form.
    Returns (values_dict, error_message). error_message is None if valid.
    """
    values = {}
    for field in config['fields']:
        if field['type'] == 'checkbox':
            values[field['name']] = 1 if request.form.get(field['name']) else 0
        else:
            val = request.form.get(field['name'], '').strip()
            if field.get('required') and not val:
                return None, f"{field['label']} is required."
            values[field['name']] = val if val else None
    return values, None


@patient_bp.route('/history/add/<record_type>', methods=['GET', 'POST'])
@patient_required
def add_history_record(record_type):
    config = HISTORY_RECORD_TYPES.get(record_type)
    if not config:
        flash('Unknown record type.', 'error')
        return redirect(url_for('patient.history'))

    _validate_history_config(config)  # defense in depth — see docstring

    patient = get_current_patient()
    patient_id = patient['patient_id']
    master_options = _get_master_options(config)

    if request.method == 'POST':
        fk_value = None
        if config.get('master_table'):
            fk_value = request.form.get(config['fk_field'])
            if not fk_value:
                flash(f"Please select a {config['fk_label'].lower()}.", 'error')
                return render_template('patient/history_form.html', patient=patient, config=config,
                                        record_type=record_type, master_options=master_options,
                                        record=None, action='add')

        values, error = _collect_form_values(config)
        if error:
            flash(error, 'error')
            return render_template('patient/history_form.html', patient=patient, config=config,
                                    record_type=record_type, master_options=master_options,
                                    record=None, action='add')

        record_id = str(uuid.uuid4())
        columns = [config['pk'], 'patient_id']
        params = [record_id, patient_id]

        if config.get('master_table'):
            columns.append(config['fk_field'])
            params.append(fk_value)

        for field in config['fields']:
            columns.append(field['name'])
            params.append(values[field['name']])

        if config.get('has_created_at'):
            columns.append('created_at')
            params.append(datetime.now().isoformat())

        columns += ['sync_status', 'recorded_by', 'is_deleted']
        params += ['pending', 'patient', 0]

        placeholders = ','.join(['?'] * len(columns))
        col_list = ','.join(columns)
        execute_query(
            f"INSERT INTO {config['table']} ({col_list}) VALUES ({placeholders})",
            tuple(params)
        )

        log_audit(session['user_id'], 'patient', f'ADD_{record_type.upper()}',
                  target_patient_id=patient_id,
                  details=f"Patient self-reported a new {config['label'].lower()} record",
                  ip_address=request.remote_addr)

        request_immediate_sync()
        flash(f"{config['label']} added — marked as Patient Reported, Not Verified.", 'success')
        return redirect(url_for('patient.history'))

    return render_template('patient/history_form.html', patient=patient, config=config,
                            record_type=record_type, master_options=master_options,
                            record=None, action='add')


def _get_own_patient_record(config, record_type, record_id, patient_id):
    """
    Fetches a record and enforces the two permission rules for edit/delete:
    it must belong to the current patient, AND it must be patient-entered
    (recorded_by='patient') — a patient can never edit or delete a
    doctor-entered clinical record through these routes, regardless of
    what's sent in the request.
    Returns the record dict, or None if either check fails.
    """
    record = execute_query(
        f"SELECT * FROM {config['table']} WHERE {config['pk']} = ? AND patient_id = ? AND is_deleted = 0",
        (record_id, patient_id), fetchone=True
    )
    if not record or record['recorded_by'] != 'patient':
        return None
    return record


@patient_bp.route('/history/edit/<record_type>/<record_id>', methods=['GET', 'POST'])
@patient_required
def edit_history_record(record_type, record_id):
    config = HISTORY_RECORD_TYPES.get(record_type)
    if not config:
        flash('Unknown record type.', 'error')
        return redirect(url_for('patient.history'))

    _validate_history_config(config)  # defense in depth — see docstring

    patient = get_current_patient()
    patient_id = patient['patient_id']

    record = _get_own_patient_record(config, record_type, record_id, patient_id)
    if not record:
        flash('Record not found, or it was entered by a clinician and cannot be edited here.', 'error')
        return redirect(url_for('patient.history'))

    master_options = _get_master_options(config)

    if request.method == 'POST':
        fk_value = None
        if config.get('master_table'):
            fk_value = request.form.get(config['fk_field'])
            if not fk_value:
                flash(f"Please select a {config['fk_label'].lower()}.", 'error')
                return render_template('patient/history_form.html', patient=patient, config=config,
                                        record_type=record_type, master_options=master_options,
                                        record=record, action='edit')

        values, error = _collect_form_values(config)
        if error:
            flash(error, 'error')
            return render_template('patient/history_form.html', patient=patient, config=config,
                                    record_type=record_type, master_options=master_options,
                                    record=record, action='edit')

        set_clauses = []
        params = []
        if config.get('master_table'):
            set_clauses.append(f"{config['fk_field']} = ?")
            params.append(fk_value)
        for field in config['fields']:
            set_clauses.append(f"{field['name']} = ?")
            params.append(values[field['name']])
        set_clauses.append("sync_status = 'pending'")

        params += [record_id, patient_id]
        execute_query(
            f"UPDATE {config['table']} SET {', '.join(set_clauses)} "
            f"WHERE {config['pk']} = ? AND patient_id = ?",
            tuple(params)
        )

        log_audit(session['user_id'], 'patient', f'EDIT_{record_type.upper()}',
                  target_patient_id=patient_id,
                  details=f"Patient edited their self-reported {config['label'].lower()} record",
                  ip_address=request.remote_addr)

        request_immediate_sync()
        flash(f"{config['label']} updated.", 'success')
        return redirect(url_for('patient.history'))

    return render_template('patient/history_form.html', patient=patient, config=config,
                            record_type=record_type, master_options=master_options,
                            record=record, action='edit')


@patient_bp.route('/history/delete/<record_type>/<record_id>', methods=['POST'])
@patient_required
def delete_history_record(record_type, record_id):
    config = HISTORY_RECORD_TYPES.get(record_type)
    if not config:
        flash('Unknown record type.', 'error')
        return redirect(url_for('patient.history'))

    _validate_history_config(config)  # defense in depth — see docstring

    patient = get_current_patient()
    patient_id = patient['patient_id']

    record = _get_own_patient_record(config, record_type, record_id, patient_id)
    if not record:
        flash('Record not found, or it was entered by a clinician and cannot be deleted here.', 'error')
        return redirect(url_for('patient.history'))

    execute_query(
        f"UPDATE {config['table']} SET is_deleted = 1, sync_status = 'pending' "
        f"WHERE {config['pk']} = ? AND patient_id = ?",
        (record_id, patient_id)
    )

    log_audit(session['user_id'], 'patient', f'DELETE_{record_type.upper()}',
              target_patient_id=patient_id,
              details=f"Patient deleted their self-reported {config['label'].lower()} record",
              ip_address=request.remote_addr)

    request_immediate_sync()
    flash(f"{config['label']} removed.", 'success')
    return redirect(url_for('patient.history'))

@patient_bp.route('/prescriptions')
@patient_required
def prescriptions():
    """
    Shows all prescriptions written for this patient.
    Most recent prescriptions appear first.
    """
    patient = get_current_patient()
    patient_id = patient['patient_id']

    all_prescriptions = execute_query(
        """SELECT p.*, u.username as doctor_username
           FROM prescriptions p
           JOIN users u ON p.doctor_user_id = u.user_id
           WHERE p.patient_id = ?
           ORDER BY p.prescription_date DESC""",
        (patient_id,), fetch=True
    )

    import json
    for prescription in (all_prescriptions or []):
        try:
            prescription['medications_list'] = json.loads(prescription.get('medications_json', '[]'))
        except Exception:
            prescription['medications_list'] = []

    log_audit(session['user_id'], 'patient', 'VIEW_PRESCRIPTIONS',
              target_patient_id=patient_id,
              details='Patient viewed prescriptions',
              ip_address=request.remote_addr)

    return render_template('patient/prescriptions.html',
        patient=patient,
        prescriptions=all_prescriptions or []
    )

@patient_bp.route('/upload', methods=['GET', 'POST'])
@patient_required
def upload_report():
    """
    GET:  Shows the upload form for medical reports
    POST: Handles file upload — saves locally first, marks for cloud sync

    Accepted file types: PDF, PNG, JPG, JPEG
    Max size: 10MB (set in config.py)
    """
    patient = get_current_patient()
    patient_id = patient['patient_id']

    if request.method == 'POST':
        if 'report_file' not in request.files:
            flash('No file selected. Please choose a file to upload.', 'error')
            return redirect(request.url)

        file = request.files['report_file']
        description = request.form.get('description', '').strip()

        if file.filename == '':
            flash('No file selected.', 'error')
            return redirect(request.url)

        from config import ALLOWED_EXTENSIONS
        filename = secure_filename(file.filename)
        file_ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

        if file_ext not in ALLOWED_EXTENSIONS:
            flash(f'File type not allowed. Please upload: {", ".join(ALLOWED_EXTENSIONS)}', 'error')
            return redirect(request.url)

        from config import LOCAL_UPLOAD_FOLDER
        patient_upload_folder = os.path.join(LOCAL_UPLOAD_FOLDER, 'reports', patient_id[:8])
        os.makedirs(patient_upload_folder, exist_ok=True)

        unique_filename = f"{uuid.uuid4().hex[:8]}_{filename}"
        file_path = os.path.join(patient_upload_folder, unique_filename)

        file.save(file_path)

        relative_path = f"uploads/reports/{patient_id[:8]}/{unique_filename}"

        report_id = str(uuid.uuid4())
        execute_query(
            """INSERT INTO medical_reports
               (report_id, patient_id, file_name, file_path, file_type, upload_date, description, sync_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (report_id, patient_id, filename, relative_path, file_ext,
             datetime.now().isoformat(), description)
        )

        log_audit(session['user_id'], 'patient', 'UPLOAD_REPORT',
                  target_patient_id=patient_id,
                  details=f'Uploaded report: {filename}',
                  ip_address=request.remote_addr)

        request_immediate_sync()

        flash('Report uploaded successfully! It will sync to cloud when internet is available.', 'success')
        return redirect(url_for('patient.view_reports'))

    return render_template('patient/uploads.html', patient=patient)


@patient_bp.route('/reports')
@patient_required
def view_reports():
    """
    Shows all medical reports uploaded by the patient.
    Displays file name, upload date, description, and sync status.
    """
    patient = get_current_patient()
    patient_id = patient['patient_id']

    reports = execute_query(
        "SELECT * FROM medical_reports WHERE patient_id = ? ORDER BY upload_date DESC",
        (patient_id,), fetch=True
    )

    return render_template('patient/reports.html',
        patient=patient,
        reports=reports or []
    )

@patient_bp.route('/qr-code')
@patient_required
def qr_code():
    """
    Shows the patient's personal QR code.
    Patient can show this to a doctor to grant 15-minute access,
    or to a paramedic for emergency access.
    Also provides a print button for making a physical QR card.
    """
    patient = get_current_patient()
    patient_id = patient['patient_id']

    from app.services.qr_service import get_qr_display_data, generate_qr_code

    qr_data = get_qr_display_data(patient_id)

    if not qr_data['qr_path']:
        generate_qr_code(patient_id)
        qr_data = get_qr_display_data(patient_id)

    log_audit(session['user_id'], 'patient', 'VIEW_QR_CODE',
              target_patient_id=patient_id,
              details='Patient viewed own QR code',
              ip_address=request.remote_addr)

    return render_template('patient/qr_code.html',
        patient=patient,
        qr_data=qr_data
    )