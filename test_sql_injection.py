import requests

BASE_URL = "http://localhost:5000"  
LOGIN_URL = f"{BASE_URL}/login"

PAYLOADS = [
    "' OR '1'='1",
    "admin'--",
    "' OR 1=1--",
    "'; DROP TABLE users;--",
    "' UNION SELECT NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL--",
]

EXPECTED_FAILURE_TEXT = "Invalid username or password"


def try_payload(payload):
    """
    Submits one payload as the username and returns whether the
    injection attempt was blocked (PASS) or succeeded (FAIL).
    """
    session = requests.Session()

    response = session.post(
        LOGIN_URL,
        data={"username": payload, "password": "anything123"},
        allow_redirects=True,
        timeout=5,
    )

    landed_on_dashboard = "dashboard" in response.url
    login_error_shown = EXPECTED_FAILURE_TEXT in response.text

    blocked = (not landed_on_dashboard) and login_error_shown
    return blocked, response.url


def main():
    print("=" * 60)
    print("MediTrack SQL Injection Test — LOGIN FORM")
    print(f"Target: {LOGIN_URL} (local only)")
    print("=" * 60)

    results = []

    for payload in PAYLOADS:
        try:
            blocked, landed_url = try_payload(payload)
        except requests.exceptions.ConnectionError:
            print("\nERROR: Could not connect to MediTrack.")
            print("Make sure it's running first with: python run.py")
            return

        status = "PASS (blocked)" if blocked else "FAIL (INJECTION SUCCEEDED!)"
        results.append((payload, status))
        print(f"\nPayload : {payload}")
        print(f"Landed on: {landed_url}")
        print(f"Result   : {status}")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, s in results if s.startswith("PASS"))
    for payload, status in results:
        print(f"  [{status.split()[0]:4}] {payload}")
    print(f"\n{passed}/{len(results)} payloads blocked.")

    if passed == len(results):
        print("\nAll injection attempts were blocked. This confirms MediTrack's")
        print("login form uses parameterized queries (safe) rather than pasting")
        print("user input directly into SQL strings (unsafe).")
    else:
        print("\nWARNING: At least one payload was NOT blocked. Review the")
        print("corresponding query in app/services/auth_service.py.")


if __name__ == "__main__":
    main()