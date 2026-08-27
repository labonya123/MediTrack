import uuid
import json
from datetime import datetime, date
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.database.local_db import execute_query, init_db
from app.services.auth_service import create_user, hash_password
from app.services.encrypt_service import hash_aadhaar, encrypt_phone
from app.services.qr_service import generate_qr_code


def seed_all():
    """
    Main function that seeds all sample data.
    Safe to run multiple times — checks if data already exists first.
    """
    print("🌱 Starting database seeding...")

    init_db()

    existing = execute_query("SELECT COUNT(*) as cnt FROM users WHERE role != 'system'", fetchone=True)
    if existing and existing['cnt'] > 0:
        print("⚠️  Database already has data. Skipping seed to avoid duplicates.")
        print("   To re-seed: delete meditrack_local.db and run again.")
        return

    seed_disease_categories()
    seed_disease_master()
    seed_allergy_categories()
    seed_allergy_master()
    seed_medication_master()
    seed_users_and_patients()
    print("\n✅ Database seeded successfully!")
    print_test_accounts()


def seed_disease_categories():
    """Inserts standard disease category groups."""
    print("  → Seeding disease categories...")
    categories = [
        ('dc001', 'Respiratory', 'lungs', 3),
        ('dc002', 'Cardiovascular', 'heart', 5),
        ('dc003', 'Endocrine', 'diabetes', 4),
        ('dc004', 'Infectious Disease', 'virus', 4),
        ('dc005', 'Neurological', 'brain', 4),
        ('dc006', 'Gastrointestinal', 'stomach', 2),
        ('dc007', 'Musculoskeletal', 'bone', 2),
        ('dc008', 'Vector-borne', 'mosquito', 4),
    ]
    for cat in categories:
        execute_query(
            "INSERT OR IGNORE INTO disease_categories VALUES (?, ?, ?, ?)", cat
        )


def seed_disease_master():
    """Inserts common diseases with ICD-10 codes."""
    print("  → Seeding disease master list...")
    diseases = [
        ('d001', 'J45', 'dc001', 'Asthma', 'दमा', 'High', 1),
        ('d002', 'E11', 'dc003', 'Type 2 Diabetes', 'मधुमेह', 'High', 1),
        ('d003', 'I10', 'dc002', 'Hypertension', 'उच्च रक्तचाप', 'High', 1),
        ('d004', 'A90', 'dc008', 'Dengue Fever', 'डेंगू बुखार', 'Critical', 0),
        ('d005', 'B50', 'dc008', 'Malaria', 'मलेरिया', 'High', 0),
        ('d006', 'A01', 'dc004', 'Typhoid', 'टाइफाइड', 'Medium', 0),
        ('d007', 'K29', 'dc006', 'Gastritis', 'जठरशोथ', 'Low', 1),
        ('d008', 'G43', 'dc005', 'Migraine', 'माइग्रेन', 'Medium', 1),
        ('d009', 'J06', 'dc001', 'Upper Respiratory Infection', 'श्वसन संक्रमण', 'Low', 0),
        ('d010', 'I21', 'dc002', 'Myocardial Infarction (Heart Attack)', 'दिल का दौरा', 'Critical', 0),
    ]
    for d in diseases:
        execute_query(
            "INSERT OR IGNORE INTO disease_master VALUES (?, ?, ?, ?, ?, ?, ?)", d
        )


def seed_allergy_categories():
    """Inserts allergy categories."""
    print("  → Seeding allergy categories...")
    cats = [
        ('ac001', 'Drug/Medication'),
        ('ac002', 'Food'),
        ('ac003', 'Environmental'),
        ('ac004', 'Insect/Venom'),
    ]
    for cat in cats:
        execute_query("INSERT OR IGNORE INTO allergy_categories VALUES (?, ?)", cat)


def seed_allergy_master():
    """Inserts common allergies."""
    print("  → Seeding allergy master list...")
    allergies = [
        ('a001', 'Penicillin', 'ac001'),
        ('a002', 'Amoxicillin', 'ac001'),
        ('a003', 'Aspirin', 'ac001'),
        ('a004', 'Sulfonamides', 'ac001'),
        ('a005', 'Peanuts', 'ac002'),
        ('a006', 'Shellfish', 'ac002'),
        ('a007', 'Eggs', 'ac002'),
        ('a008', 'Milk/Lactose', 'ac002'),
        ('a009', 'Pollen', 'ac003'),
        ('a010', 'Dust Mites', 'ac003'),
        ('a011', 'Bee Sting', 'ac004'),
        ('a012', 'Ibuprofen', 'ac001'),
    ]
    for a in allergies:
        execute_query("INSERT OR IGNORE INTO allergy_master VALUES (?, ?, ?)", a)


def seed_medication_master():
    """Inserts common medications."""
    print("  → Seeding medication master list...")
    meds = [
        ('m001', 'Metformin', 'Glucophage', 'Biguanide', json.dumps(['Kidney disease', 'Liver disease'])),
        ('m002', 'Amlodipine', 'Norvasc', 'Calcium Channel Blocker', json.dumps(['Severe hypotension'])),
        ('m003', 'Salbutamol', 'Ventolin', 'Beta-2 Agonist', json.dumps(['Hypersensitivity to salbutamol'])),
        ('m004', 'Omeprazole', 'Prilosec', 'Proton Pump Inhibitor', json.dumps(['Hypersensitivity'])),
        ('m005', 'Paracetamol', 'Crocin', 'Analgesic', json.dumps(['Liver disease', 'Alcohol use'])),
        ('m006', 'Amoxicillin', 'Amoxil', 'Penicillin Antibiotic', json.dumps(['Penicillin allergy', 'Cephalosporin allergy'])),
        ('m007', 'Atenolol', 'Tenormin', 'Beta Blocker', json.dumps(['Asthma', 'Heart block'])),
        ('m008', 'Cetirizine', 'Zyrtec', 'Antihistamine', json.dumps(['Hypersensitivity'])),
    ]
    for m in meds:
        execute_query(
            "INSERT OR IGNORE INTO medication_master VALUES (?, ?, ?, ?, ?)", m
        )


def seed_users_and_patients():
    """Creates all test user accounts and patient records."""
    print("  → Seeding users and patient records...")
    now = datetime.now().isoformat()

    # Create Admin
    admin_result = create_user('admin', 'admin123', 'admin')
    print(f"     Admin created: {admin_result}")

    # Create Doctor 
    doctor_result = create_user('dr_sharma', 'doctor123', 'doctor')
    doctor_id = doctor_result.get('user_id')
    print(f"     Doctor created: {doctor_result}")

    # Create Paramedic 
    para_result = create_user('paramedic1', 'para123', 'paramedic')
    print(f"     Paramedic created: {para_result}")

    # Create Patient 1: Rahul Kumar (has diabetes, hypertension) 
    patient1_result = create_user('rahul_kumar', 'patient123', 'patient')
    patient1_user_id = patient1_result.get('user_id')
    patient1_id = str(uuid.uuid4())

    execute_query(
        """INSERT INTO patients (patient_id, user_id, abha_id, first_name, last_name, gender,
           date_of_birth, blood_group, phone_number_encrypted, aadhaar_hash,
           village_name, district, state, has_chronic_disease, has_life_threat_allergy,
           is_pregnant, organ_donor_status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (patient1_id, patient1_user_id, 'ABHA-2023-001', 'Rahul', 'Kumar', 'Male',
         '1985-06-15', 'B+', encrypt_phone('9876543210'),
         hash_aadhaar('123412341234'), 'Rampur', 'Varanasi', 'Uttar Pradesh',
         1, 0, 0, 'No', now, now)
    )

    # Patient 1 diseases
    execute_query(
        "INSERT INTO patient_diseases VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), patient1_id, 'd002', '2020-03-10', 'Active', 'Moderate', 1, '2026-01-15', 'Controlled with medication', 'pending', 'clinical', 0)
    )
    execute_query(
        "INSERT INTO patient_diseases VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), patient1_id, 'd003', '2021-07-20', 'Active', 'Mild', 1, '2026-01-15', 'On Amlodipine', 'pending', 'clinical', 0)
    )

    # Patient 1 medications
    execute_query(
        "INSERT INTO patient_medications VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), patient1_id, 'm001', 1, '2020-03-15', None, '500mg', 'Twice daily', 'Dr. Sharma', 'Take with meals', 'pending')
    )
    execute_query(
        "INSERT INTO patient_medications VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), patient1_id, 'm002', 1, '2021-08-01', None, '5mg', 'Once daily', 'Dr. Sharma', 'Take in morning', 'pending')
    )

    # Patient 1 emergency contacts
    execute_query(
        "INSERT INTO emergency_contacts VALUES (?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), patient1_id, 'Sunita Kumar', 'Wife', '9876543211', 1, 'pending')
    )

    # Create Patient 2: Priya Devi (has asthma, penicillin allergy) 
    patient2_result = create_user('priya_devi', 'patient123', 'patient')
    patient2_user_id = patient2_result.get('user_id')
    patient2_id = str(uuid.uuid4())

    execute_query(
        """INSERT INTO patients (patient_id, user_id, abha_id, first_name, last_name, gender,
           date_of_birth, blood_group, phone_number_encrypted, aadhaar_hash,
           village_name, district, state, has_chronic_disease, has_life_threat_allergy,
           is_pregnant, organ_donor_status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (patient2_id, patient2_user_id, 'ABHA-2023-002', 'Priya', 'Devi', 'Female',
         '1995-11-23', 'O+', encrypt_phone('9765432109'),
         hash_aadhaar('432143214321'), 'Sultanpur', 'Lucknow', 'Uttar Pradesh',
         1, 1, 0, 'Yes', now, now)
    )

    # Patient 2 disease: Asthma
    execute_query(
        "INSERT INTO patient_diseases VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), patient2_id, 'd001', '2018-04-05', 'Active', 'Moderate', 1, '2026-01-10', 'Uses inhaler daily', 'pending', 'clinical', 0)
    )

    # Patient 2 CRITICAL allergy: Penicillin (life threatening)
    execute_query(
        "INSERT INTO patient_allergies VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), patient2_id, 'a001', 'Anaphylaxis', 'Life-threatening', 1, 1, now, 'pending', None, 'clinical', 0)
    )
    execute_query(
        "INSERT INTO patient_allergies VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), patient2_id, 'a002', 'Severe rash and breathing difficulty', 'Life-threatening', 1, 1, now, 'pending', None, 'clinical', 0)
    )

    # Patient 2 medication
    execute_query(
        "INSERT INTO patient_medications VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), patient2_id, 'm003', 1, '2018-04-10', None, '100mcg', 'As needed', 'Dr. Sharma', 'Carry inhaler always', 'pending')
    )

    # Patient 2 emergency contact
    execute_query(
        "INSERT INTO emergency_contacts VALUES (?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), patient2_id, 'Ram Devi', 'Father', '9765432110', 1, 'pending')
    )

    if doctor_id:
        execute_query(
            """INSERT INTO prescriptions VALUES (?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), patient1_id, doctor_id, '2026-01-15',
             'Type 2 Diabetes - Follow up',
             json.dumps([
                 {'name': 'Metformin', 'dose': '500mg', 'frequency': 'Twice daily with meals'},
                 {'name': 'Amlodipine', 'dose': '5mg', 'frequency': 'Once daily morning'}
             ]),
             'Continue current medications. Reduce sugar intake. Walk 30 minutes daily.',
             '2026-04-15', 'pending')
        )

    # Generate QR codes for both patients
    generate_qr_code(patient1_id)
    generate_qr_code(patient2_id)

    # Create emergency snapshots 
    for pid, bg in [(patient1_id, 'B+'), (patient2_id, 'O+')]:
        execute_query(
            """INSERT OR REPLACE INTO patient_emergency_snapshot
               (patient_id, blood_group, active_diseases_json, life_threat_allergies_json,
                current_medications_json, emergency_contacts_json, last_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (pid, bg,
             json.dumps([{'disease_name': 'See full record', 'status': 'Active'}]),
             json.dumps([{'allergy_name': 'Check allergies section'}]),
             json.dumps([{'generic_name': 'See medications section'}]),
             json.dumps([{'name': 'Emergency Contact', 'phone_number': 'See contacts'}]),
             now)
        )

    print(f"     Patient 1 (Rahul Kumar) ID: {patient1_id[:8]}...")
    print(f"     Patient 2 (Priya Devi) ID: {patient2_id[:8]}...")


def print_test_accounts():
    """Prints all test login credentials to the console."""
    print("\n" + "="*50)
    print("🔑 TEST LOGIN CREDENTIALS")
    print("="*50)
    print("  ADMIN:     username=admin        password=admin123")
    print("  DOCTOR:    username=dr_sharma    password=doctor123")
    print("  PARAMEDIC: username=paramedic1   password=para123")
    print("  PATIENT 1: username=rahul_kumar  password=patient123")
    print("  PATIENT 2: username=priya_devi   password=patient123")
    print("="*50)
    print("\n🌐 Open your browser and go to: http://localhost:5000")
    print("="*50 + "\n")


if __name__ == '__main__':
    seed_all()
