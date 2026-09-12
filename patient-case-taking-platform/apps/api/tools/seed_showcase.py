"""Create one synthetic accepted intake through local public APIs for a showcase."""

import argparse
import json
from urllib.parse import urlparse
from uuid import uuid4

import httpx


def seed(base_url: str) -> dict[str, str]:
    parsed = urlparse(base_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.scheme != "http":
        raise ValueError("Showcase seeding is restricted to a local HTTP API")
    ids = {key: str(uuid4()) for key in (
        "tenant_id", "facility_id", "patient_id", "encounter_id", "doctor_id",
    )}
    with httpx.Client(base_url=base_url, timeout=30) as client:
        token = client.post("/api/v1/auth/token", params={
            "user_id": ids["patient_id"], "email": "patient@showcase.example.test",
            "role": "patient", "tenant_id": ids["tenant_id"],
            "facility_ids": ids["facility_id"],
        })
        token.raise_for_status()
        client.headers["Authorization"] = f"Bearer {token.json()['token']}"
        session = client.post("/api/v1/auth/kiosk/session", params={
            "facility_id": ids["facility_id"], "language": "en",
        })
        session.raise_for_status()
        consent = client.post("/api/v1/patient-portal/me/consents", json={
            "encounter_id": ids["encounter_id"], "document_upload": True,
            "retain_audio": False, "expires_in_hours": 24,
        })
        consent.raise_for_status()
        complaint = "Synthetic showcase: headache since this morning"
        intake = client.post("/api/v1/patient-portal/me/intakes", headers={
            "Idempotency-Key": f"showcase-{ids['encounter_id']}",
        }, json={
            "facility_id": ids["facility_id"], "encounter_id": ids["encounter_id"],
            "session_id": session.json()["session_id"], "consent_id": consent.json()["id"],
            "language": "en", "chief_complaint": complaint,
            "confirmed_answers": {"site": "Forehead", "onset": "This morning",
                                  "severity": "Mild", "associated_symptoms": "None reported"},
            "summary_draft": {"chief_complaint": complaint,
                              "history_of_present_illness": ["Synthetic intake for software demonstration"],
                              "uncertainties": ["Clinician assessment required"]},
            "decision": "accepted", "provider": "mock",
        })
        intake.raise_for_status()
    return {**ids, "intake_id": intake.json()["id"],
            "clinical_email": "doctor@showcase.example.test"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    print(json.dumps(seed(args.api_url), indent=2))
