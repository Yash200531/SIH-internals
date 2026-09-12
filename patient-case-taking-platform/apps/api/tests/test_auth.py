"""Tests for auth, RBAC, sessions, break-glass."""
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_create_token():
    r = client.post("/api/v1/auth/token", params={
        "user_id": "user1",
        "email": "test@example.com",
        "role": "doctor",
        "tenant_id": "tenant1",
        "facility_ids": ["fac1"]
    })
    assert r.status_code == 200
    assert "token" in r.json()


def test_kiosk_session_lifecycle():
    facility_id = str(uuid4())
    # Create
    r = client.post("/api/v1/auth/kiosk/session", params={"facility_id": facility_id})
    assert r.status_code == 200
    session_id = r.json()["session_id"]
    assert r.json()["state"] == "initializing"

    # Touch
    r2 = client.post(f"/api/v1/auth/kiosk/session/{session_id}/touch")
    assert r2.status_code == 200

    # Expire
    r3 = client.post(f"/api/v1/auth/kiosk/session/{session_id}/expire")
    assert r3.status_code == 200


def test_device_registration():
    r = client.post("/api/v1/auth/devices", params={
        "device_id": "kiosk-001",
        "facility_id": str(uuid4()),
        "device_type": "kiosk",
        "device_name": "Reception Kiosk"
    })
    assert r.status_code == 200
    assert r.json()["is_active"] is True
