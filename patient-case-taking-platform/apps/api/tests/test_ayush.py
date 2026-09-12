"""Tests for AYUSH assessment and intervention endpoints."""
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_create_ayush_assessment():
    patient_id = uuid4()
    encounter_id = uuid4()
    r = client.post("/api/v1/ayush/assessments", json={
        "patient_id": str(patient_id),
        "encounter_id": str(encounter_id),
        "ayush_system": "ayurveda",
        "prakriti": {"vata_prakriti": 40, "pitta_prakriti": 35, "kapha_prakriti": 25},
        "vikriti": {"vata_vikriti": 60, "pitta_vikriti": 30, "kapha_vikriti": 10},
        "agni": {"type": "samagni", "status": "normal"}
    })
    assert r.status_code == 201
    data = r.json()
    assert data["ayush_system"] == "ayurveda"
    assert data["status"] == "draft"


def test_get_ayush_assessment():
    patient_id = uuid4()
    encounter_id = uuid4()
    r = client.post("/api/v1/ayush/assessments", json={
        "patient_id": str(patient_id),
        "encounter_id": str(encounter_id),
        "ayush_system": "ayurveda"
    })
    assessment_id = r.json()["id"]
    r2 = client.get(f"/api/v1/ayush/assessments/{assessment_id}")
    assert r2.status_code == 200


def test_confirm_ayush_assessment():
    patient_id = uuid4()
    encounter_id = uuid4()
    r = client.post("/api/v1/ayush/assessments", json={
        "patient_id": str(patient_id),
        "encounter_id": str(encounter_id),
        "ayush_system": "ayurveda"
    })
    assessment_id = r.json()["id"]
    r2 = client.post(f"/api/v1/ayush/assessments/{assessment_id}/confirm")
    assert r2.status_code == 200
    assert r2.json()["status"] == "confirmed"


def test_create_ayush_intervention():
    patient_id = uuid4()
    r = client.post("/api/v1/ayush/interventions", json={
        "patient_id": str(patient_id),
        "intervention_type": "herbal",
        "intervention_name": "Ashwagandha",
        "dosage": {"amount": "500mg", "frequency": "twice daily", "duration": "30 days"},
        "indicated_for": {"condition": "stress", "dosha": "vata"}
    })
    assert r.status_code == 201
    assert r.json()["response_status"] == "prescribed"


def test_fhir_patient_export():
    r = client.get("/api/v1/fhir/patient/test-patient-id")
    assert r.status_code == 200
    data = r.json()
    assert data["resourceType"] == "Patient"


def test_fhir_encounter_export():
    r = client.get("/api/v1/fhir/encounter/test-encounter-id")
    assert r.status_code == 200
    assert r.json()["resourceType"] == "Encounter"
