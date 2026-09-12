from uuid import uuid4

from fastapi.testclient import TestClient

from app.auth.token import create_dev_token
from app.main import app
from app.routers.patients import _patients

client = TestClient(app)
TENANT_ID = uuid4()
_token = create_dev_token("test-patient-user", "test@test.com", "doctor", str(TENANT_ID), [])
_headers = {"Authorization": f"Bearer {_token}"}


def _clear():
    _patients.clear()


def test_create_patient():
    _clear()
    r = client.post(
        "/api/v1/patients",
        params={"tenant_id": str(TENANT_ID)},
        json={"full_name": "Ram Kumar", "phone": "9876543210"},
        headers=_headers,
    )
    assert r.status_code == 201
    data = r.json()
    assert data["full_name"] == "Ram Kumar"
    assert data["internal_mrn"].startswith("MRN-")
    assert data["tenant_id"] == str(TENANT_ID)


def test_get_patient():
    _clear()
    r = client.post(
        "/api/v1/patients",
        params={"tenant_id": str(TENANT_ID)},
        json={"full_name": "Sita Devi"},
        headers=_headers,
    )
    pid = r.json()["id"]
    r2 = client.get(f"/api/v1/patients/{pid}", headers=_headers)
    assert r2.status_code == 200
    assert r2.json()["full_name"] == "Sita Devi"


def test_search_patient():
    _clear()
    client.post(
        "/api/v1/patients",
        params={"tenant_id": str(TENANT_ID)},
        json={"full_name": "Arjun Patel", "phone": "9999900000"},
        headers=_headers,
    )
    r = client.get(
        "/api/v1/patients/search",
        params={"query": "Arjun", "tenant_id": str(TENANT_ID)},
        headers=_headers,
    )
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["full_name"] == "Arjun Patel"


def test_abha_linking():
    _clear()
    r = client.post(
        "/api/v1/patients",
        params={"tenant_id": str(TENANT_ID)},
        json={"full_name": "Test ABHA"},
        headers=_headers,
    )
    pid = r.json()["id"]
    r2 = client.post(
        f"/api/v1/patients/{pid}/abha",
        params={"abha_number": "1234-5678-9012", "abha_address": "ram@abdm"},
        headers=_headers,
    )
    assert r2.status_code == 201
    assert r2.json()["abha_verified"] is True
