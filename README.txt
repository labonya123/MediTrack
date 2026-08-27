============================================================
  MediTrack — Cloud-Based Emergency Medical Record System
  Version 1.0.0 | Phase 1 | BITS Pilani Project
============================================================

HOW TO RUN 
--------------------------------------------

WINDOWS:
  1. Double-click "run.bat"
  2. Wait for it to install packages (first time only)
  3. Open your browser at: http://localhost:5000
  4. Done!

MAC or LINUX:
  1. Open Terminal
  2. Type: cd /path/to/meditrack
  3. Type: chmod +x run.sh
  4. Type: ./run.sh
  5. Open your browser at: http://localhost:5000

REQUIREMENT: Python 3.8 or higher must be installed.
  Download from: https://www.python.org/downloads/
  IMPORTANT: Check "Add Python to PATH" during Windows install.

============================================================
TEST LOGIN ACCOUNTS
============================================================

  ADMIN:
    Username: admin
    Password: admin123

  DOCTOR:
    Username: dr_sharma
    Password: doctor123

  PARAMEDIC:
    Username: paramedic1
    Password: para123

  PATIENT 1 (Rahul Kumar - Diabetes, Hypertension):
    Username: rahul_kumar
    Password: patient123

  PATIENT 2 (Priya Devi - Asthma, Penicillin Allergy):
    Username: priya_devi
    Password: patient123

============================================================
HOW THE SYSTEM WORKS
============================================================

FOR PATIENTS:
  - Log in to see your medical history and prescriptions
  - Upload medical reports (PDFs or images)
  - View and print your QR code card

FOR DOCTORS:
  - Log in and click "Scan QR Code"
  - Scan patient's QR code to get 15-minute access
  - View full records and write prescriptions
  - Session expires automatically after 15 minutes
  - Must scan QR again for new access

FOR PARAMEDICS (EMERGENCY):
  - Scan patient's QR code (even without internet)
  - See blood group, life-threatening allergies,
    current medications, and emergency contacts
  - No password needed for patient

FOR ADMIN:
  - Manage doctor and paramedic accounts
  - View anonymised health statistics
  - Monitor system activity

============================================================
FILE STRUCTURE
============================================================

meditrack/
├── run.py              ← Main application entry point
├── run.bat             ← Windows launcher (double-click)
├── run.sh              ← Mac/Linux launcher
├── config.py           ← Settings (change for cloud)
├── requirements.txt    ← Python packages list
├── README.txt          ← This file
└── app/
    ├── database/       ← Database setup and sample data
    ├── models/         ← Data structure definitions
    ├── routes/         ← Page logic for each role
    ├── services/       ← Core features (QR, sync, encrypt)
    ├── templates/      ← HTML pages
    └── static/         ← CSS, JS, uploaded files

============================================================
CLOUD SETUP (Phase 2)
============================================================

To enable cloud sync to Supabase:
  1. Create free account at: https://supabase.com
  2. Create a new project
  3. Open config.py
  4. Set USE_CLOUD = True
  5. Fill in SUPABASE_URL and SUPABASE_KEY
  6. Restart the app

That's it! Data will automatically sync to cloud
when internet is available.

============================================================
TROUBLESHOOTING
============================================================

"Python not found":
  Install Python from python.org and check "Add to PATH"

"Port already in use":
  Change PORT = 5000 to PORT = 5001 in config.py

"Module not found" error:
  Run: pip install -r requirements.txt

"Database error" on fresh start:
  Delete meditrack_local.db file and restart

============================================================
PROJECT INFO
============================================================

  Project:    MediTrack — Phase 1
  Student:    Labonya Pragna Chakma (2023EBCS217)
  Group:      16
  Supervisor: Dr. Imandi Raju
  Institute:  BITS Pilani
  Date:       February 2026

============================================================
