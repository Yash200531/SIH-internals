from uuid import uuid4

from fastapi.testclient import TestClient

from app.auth.token import create_dev_token
from app.main import app
from app.routers.encounters import _encounters

client = TestClient(app)
TENANT_ID = uuid4()
FACILITY_ID = uuid4()
PATIENT_ID = uuid4()
_token = create_dev_token("test-encounter-user", "test@test.com", "doctor", str(TENANT_ID), [])
_headers = {"Authorization": f"Bearer {_token}"}


def _clear():
    _encounters.clear()


def test_create_encounter():
    _clear()
    r = client.post(
        "/api/v1/encounters",
        params={"tenant_id": str(TENANT_ID)},
        json={
            "patient_id": str(PATIENT_ID),
            "facility_id": str(FACILITY_ID),
            "chief_complaint": "Fever for 3 days",
        },
        headers=_headers,
    )
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "intake"
    assert data["patient_id"] == str(PATIENT_ID)


def test_encounter_state_transitions():
    _clear()
    r = client.post(
        "/api/v1/encounters",
        params={"tenant_id": str(TENANT_ID)},
        json={"patient_id": str(PATIENT_ID), "facility_id": str(FACILITY_ID)},
        headers=_headers,
    )
    eid = r.json()["id"]

    for next_status in ("in_progress", "draft", "signed"):
        r2 = client.put(
            f"/api/v1/encounters/{eid}/status",
            json={"status": next_status},
            headers=_headers,
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == next_status


def test_invalid_transition_rejected():
    _clear()
    r = client.post(
        "/api/v1/encounters",
        params={"tenant_id": str(TENANT_ID)},
        json={"patient_id": str(PATIENT_ID), "facility_id": str(FACILITY_ID)},
        headers=_headers,
    )
    eid = r.json()["id"]

    r2 = client.put(
        f"/api/v1/encounters/{eid}/status",
        json={"status": "signed"},
        headers=_headers,
    )
    assert r2.status_code == 422
