"""E2E smoke test: start API server, hit ASR + OCR endpoints."""
import os
import subprocess
import sys
import time
from uuid import uuid4

import pytest

if os.getenv("RUN_SERVER_SMOKE_TESTS") != "1":
    pytest.skip("set RUN_SERVER_SMOKE_TESTS=1 to run subprocess smoke tests", allow_module_level=True)

# Set env vars for child process
env = os.environ.copy()
env["ENABLE_DEMO_ROUTES"] = "true"
env["DOCUMENT_WORKFLOW_ENABLED"] = "true"
env["ASR_PROVIDER"] = os.getenv("ASR_PROVIDER", "mock")
env["OCR_PROVIDER"] = os.getenv("OCR_PROVIDER", "mock")

api_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

# Start server
print("Starting API server...")
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8004"],
    cwd=api_dir,
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)

try:
    import requests
    # Wait for server
    for i in range(60):
        try:
            r = requests.get("http://127.0.0.1:8004/healthz", timeout=2)
            if r.status_code == 200:
                print(f"Server ready after {i+1}s")
                break
        except Exception:
            time.sleep(1)
    else:
        # Dump server output for debugging
        print("Server failed to start. Output:")
        proc.terminate()
        out = proc.communicate(timeout=5)[0]
        print(out.decode()[-2000:] if out else "No output")
        sys.exit(1)

    BASE = "http://127.0.0.1:8004"

    # Requires migrated local PostgreSQL: speech never bypasses stored consent.
    tenant, patient, facility, encounter = (str(uuid4()) for _ in range(4))
    access = requests.post(f"{BASE}/api/v1/auth/token", params={
        "user_id": patient, "email": "patient@smoke.example.test", "role": "patient",
        "tenant_id": tenant, "facility_ids": facility,
    }, timeout=10)
    access.raise_for_status()
    headers = {"Authorization": f"Bearer {access.json()['token']}"}
    session = requests.post(f"{BASE}/api/v1/patient-portal/me/sessions",
                            headers={**headers, "Idempotency-Key": str(uuid4())},
                            json={"facility_id": facility, "language": "hi"}, timeout=15)
    session.raise_for_status()
    encounter = session.json()["encounter_id"]
    consent = requests.post(f"{BASE}/api/v1/patient-portal/me/consents", headers=headers,
                            json={"encounter_id": encounter}, timeout=15)
    consent.raise_for_status()

    # Test ASR
    print("\n=== ASR Transcribe ===")
    audio_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_audio.wav")
    with open(audio_path, "rb") as f:
        r = requests.post(f"{BASE}/api/v1/asr/transcribe",
                         files={"file": ("test.wav", f, "audio/wav")},
                         data={"language": "hi", "tenant_id": tenant, "session_id": session.json()["id"],
                               "encounter_id": encounter, "consent_id": consent.json()["id"]},
                         headers=headers,
                         timeout=120)
    print(f"Status: {r.status_code}")
    data = r.json()
    print(f"Text: {data.get('text', 'N/A')}")
    print(f"Provider: {data.get('provider', 'N/A')}")
    print(f"Duration: {data.get('duration_ms', 'N/A')}ms")
    assert r.status_code == 200, f"ASR failed: {r.status_code}"

    # Test OCR
    print("\n=== OCR Recognize ===")
    img_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_ocr_image.png")
    with open(img_path, "rb") as f:
        r = requests.post(f"{BASE}/api/v1/ocr/recognize",
                         files={"file": ("test.png", f, "image/png")},
                         timeout=300)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"Text:\n{data.get('text', 'N/A')}")
        print(f"Regions: {len(data.get('regions', []))}")
        print(f"Provider: {data.get('provider', 'N/A')}")
        print(f"Duration: {data.get('duration_ms', 'N/A')}ms")
    else:
        print(f"Error body: {r.text[:500]}")

    assert r.status_code == 200, f"OCR failed: {r.status_code} {r.text[:500]}"
    print("\n=== ALL SMOKE TESTS PASSED ===")

finally:
    proc.terminate()
    proc.wait(timeout=10)
    print("Server stopped.")
