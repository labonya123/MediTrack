import hashlib
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from config import ENCRYPTION_KEY

try:
    from cryptography.fernet import Fernet
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


def _get_fernet():
    """
    Creates and returns a Fernet encryption object using the app's encryption key.
    Fernet provides symmetric encryption (same key to encrypt and decrypt).
    Returns: Fernet object
    """
    key = ENCRYPTION_KEY.encode('utf-8')[:32].ljust(32, b'0')
    encoded_key = base64.urlsafe_b64encode(key)
    return Fernet(encoded_key)


def hash_aadhaar(aadhaar_number):
    """
    Creates a one-way SHA-256 hash of an Aadhaar number.
    The original Aadhaar number CANNOT be recovered from this hash.
    This is intentional — we only need to verify identity, not store raw Aadhaar.

    Parameters:
        aadhaar_number - The 12-digit Aadhaar number as string
    Returns:
        64-character hex string hash, or None if input is empty
    """
    if not aadhaar_number:
        return None

    clean_aadhaar = aadhaar_number.replace(' ', '').replace('-', '')

    salt = "meditrack_aadhaar_salt_2026"
    salted = f"{salt}{clean_aadhaar}{salt}"

    return hashlib.sha256(salted.encode('utf-8')).hexdigest()


def encrypt_phone(phone_number):
    """
    Encrypts a phone number for secure storage.
    Unlike Aadhaar, phone numbers CAN be decrypted when needed
    (e.g., to show to admin for verification purposes).

    Parameters:
        phone_number - Phone number string
    Returns:
        Encrypted string, or original if encryption library unavailable
    """
    if not phone_number:
        return None

    if not CRYPTO_AVAILABLE:
        return base64.b64encode(phone_number.encode()).decode()

    try:
        f = _get_fernet()
        return f.encrypt(phone_number.encode()).decode()
    except Exception:
        return base64.b64encode(phone_number.encode()).decode()


def decrypt_phone(encrypted_phone):
    """
    Decrypts an encrypted phone number back to its original form.
    Only used when authorized access is needed.

    Parameters:
        encrypted_phone - The encrypted phone number string
    Returns:
        Original phone number string, or placeholder if decryption fails
    """
    if not encrypted_phone:
        return None

    if not CRYPTO_AVAILABLE:
        try:
            return base64.b64decode(encrypted_phone.encode()).decode()
        except Exception:
            return "***encrypted***"

    try:
        f = _get_fernet()
        return f.decrypt(encrypted_phone.encode()).decode()
    except Exception:
        try:
            return base64.b64decode(encrypted_phone.encode()).decode()
        except Exception:
            return "***encrypted***"


def anonymise_patient(patient_dict):
    """
    Removes all personally identifiable information (PII) from a patient record.
    Used when Admin views data — they see health trends, not personal details.

    What is REMOVED:
    - first_name, last_name (replaced with Anonymous)
    - phone_number (removed)
    - aadhaar_hash (removed)
    - abha_id (removed)

    What is KEPT (for health tracking):
    - patient_id (as anonymous ID)
    - blood_group
    - date_of_birth (only year, not full date)
    - village_name, district, state (for geographic tracking)
    - health flags (chronic disease, pregnancy, etc.)

    Parameters:
        patient_dict - Dictionary of patient data
    Returns:
        Anonymised patient dictionary safe for admin viewing
    """
    if not patient_dict:
        return None

    anon = dict(patient_dict)

    anon['first_name'] = 'Anonymous'
    anon['last_name'] = f"Patient-{str(anon.get('patient_id', ''))[:8]}"
    anon.pop('phone_number_encrypted', None)
    anon.pop('aadhaar_hash', None)
    anon.pop('abha_id', None)
    anon.pop('qr_code_path', None)
    anon.pop('user_id', None)

    dob = anon.get('date_of_birth', '')
    if dob and len(dob) >= 4:
        anon['birth_year'] = dob[:4]  
    anon.pop('date_of_birth', None)

    return anon
