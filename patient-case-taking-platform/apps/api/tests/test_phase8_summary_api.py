"""Authorized HTTP contract and complete mock-provider Phase 8 workflow tests."""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.token import create_dev_token
from app.config import settings
from app.llm.providers import MockClinicalProvider
from app.llm.service import LLMRouter
from app.main import app
from app.summary_workflow.context import InMemorySummaryContextRepository
from app.summary_workflow.dependencies import (
    _require_enabled,
    get_summary_context_repository,
    get_summary_repository,
    get_summary_workflow_service,
)
from app.summary_workflow.repository import InMemorySummaryRepository
from app.summary_workflow.service import SummaryWorkflowService

client = TestClient(app)


@pytest.fixture
def workflow():
    repository = InMemorySummaryRepository()
    contexts = InMemorySummaryContextRepository()
    service = SummaryWorkflowService(repository, LLMRouter(MockClinicalProvider()))
    app.dependency_overrides[get_summary_repository] = lambda: repository
    app.dependency_overrides[get_summary_context_repository] = lambda: contexts
    app.dependency_overrides[get_summary_workflow_service] = lambda: service
    yield repository, contexts
    for dependency in (
        get_summary_repository,
        get_summary_context_repository,
        get_summary_workflow_service,
    ):
        app.dependency_overrides.pop(dependency, None)


def _headers(tenant_id, facility_id, role="doctor", key=None):
    token = create_dev_token(
        str(uuid4()), f"{role}@example.test", role, str(tenant_id), [str(facility_id)]
    )
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


def _context(tenant_id, facility_id, patient_id, encounter_id, role="doctor"):
    return client.put(
        "/api/v1/summary-workflows/contexts",
        headers=_headers(tenant_id, facility_id, role),
        json={
            "facility_id": str(facility_id),
            "patient_id": str(patient_id),
            "encounter_id": str(encounter_id),
            "language": "en",
            "chief_complaint": "I cannot breathe",
            "confirmed_answers": {"site": "chest", "severity": 8},
        },
    )


def _generate(tenant_id, facility_id, patient_id, encounter_id, role="doctor"):
    return client.post(
        "/api/v1/summary-workflows/generate",
        headers=_headers(tenant_id, facility_id, role, "generate-http-1"),
        json={
            "facility_id": str(facility_id),
            "patient_id": str(patient_id),
            "encounter_id": str(encounter_id),
            "language": "en",
        },
    )


def test_complete_context_generate_edit_review_and_sign_workflow(workflow):
    tenant_id, facility_id, patient_id, encounter_id = (uuid4() for _ in range(4))
    context = _context(tenant_id, facility_id, patient_id, encounter_id)
    assert context.status_code == 200
    assert "RF-RESP-001" in context.json()["deterministic_red_flags"]

    injected = client.post(
        "/api/v1/summary-workflows/generate",
        headers=_headers(tenant_id, facility_id, "doctor", "injected-payload"),
        json={
            "facility_id": str(facility_id),
            "patient_id": str(patient_id),
            "encounter_id": str(encounter_id),
            "language": "en",
            "chief_complaint": "client supplied narrative is forbidden",
        },
    )
    assert injected.status_code == 422

    generated = _generate(tenant_id, facility_id, patient_id, encounter_id)
    assert generated.status_code == 201
    draft = generated.json()
    assert draft["provider"] == "mock"
    assert draft["content"]["chief_complaint"] == "I cannot breathe"
    assert "RF-RESP-001" in draft["content"]["red_flags"]

    edited_content = {**draft["content"], "history_of_present_illness": ["Doctor edit"]}
    edited = client.patch(
        f"/api/v1/summary-workflows/{draft['id']}/draft",
        headers=_headers(tenant_id, facility_id),
        json={"expected_version": 1, "content": edited_content},
    )
    assert edited.status_code == 200
    assert any(item["source_type"] == "clinician_edit" for item in edited.json()["evidence"])
    submitted = client.post(
        f"/api/v1/summary-workflows/{draft['id']}/submit-review",
        headers=_headers(tenant_id, facility_id, "nurse"),
        json={"expected_version": edited.json()["lock_version"]},
    )
    assert submitted.status_code == 200
    signed = client.post(
        f"/api/v1/summary-workflows/{draft['id']}/sign",
        headers=_headers(tenant_id, facility_id),
        json={"expected_version": submitted.json()["lock_version"]},
    )
    assert signed.status_code == 200
    assert signed.json()["status"] == "signed"
    assert len(signed.json()["signature_sha256"]) == 64

    history = client.get(
        f"/api/v1/summary-workflows/{draft['id']}/history",
        headers=_headers(tenant_id, facility_id),
    )
    assert [item["action"] for item in history.json()] == [
        "generated",
        "edited",
        "submitted",
        "signed",
    ]


def test_nurse_cannot_sign_and_wrong_facility_cannot_generate(workflow):
    tenant_id, facility_id, patient_id, encounter_id = (uuid4() for _ in range(4))
    assert _context(tenant_id, facility_id, patient_id, encounter_id).status_code == 200
    draft = _generate(tenant_id, facility_id, patient_id, encounter_id).json()
    denied = client.post(
        f"/api/v1/summary-workflows/{draft['id']}/sign",
        headers=_headers(tenant_id, facility_id, "nurse"),
        json={"expected_version": 1},
    )
    assert denied.status_code in {403, 422}
    wrong_facility = client.post(
        "/api/v1/summary-workflows/generate",
        headers=_headers(tenant_id, uuid4(), "doctor", "wrong-facility"),
        json={
            "facility_id": str(facility_id),
            "patient_id": str(patient_id),
            "encounter_id": str(encounter_id),
            "language": "en",
        },
    )
    assert wrong_facility.status_code == 403


def test_reject_and_regenerate_creates_new_lineage_version(workflow):
    tenant_id, facility_id, patient_id, encounter_id = (uuid4() for _ in range(4))
    assert _context(tenant_id, facility_id, patient_id, encounter_id).status_code == 200
    draft = _generate(tenant_id, facility_id, patient_id, encounter_id).json()
    rejected = client.post(
        f"/api/v1/summary-workflows/{draft['id']}/reject",
        headers=_headers(tenant_id, facility_id),
        json={"expected_version": 1, "reason": "Clarify the source"},
    ).json()
    regenerated = client.post(
        f"/api/v1/summary-workflows/{draft['id']}/regenerate",
        headers=_headers(tenant_id, facility_id, "doctor", "regen-http-1"),
        json={
            "facility_id": str(facility_id),
            "patient_id": str(patient_id),
            "encounter_id": str(encounter_id),
            "language": "en",
            "expected_version": rejected["lock_version"],
        },
    )
    assert regenerated.status_code == 201
    replacement = regenerated.json()
    assert replacement["parent_summary_id"] == draft["id"]
    assert replacement["generation"] == 2


def test_non_clinical_role_is_rejected(workflow):
    tenant_id, facility_id, patient_id, encounter_id = (uuid4() for _ in range(4))
    response = _context(tenant_id, facility_id, patient_id, encounter_id, role="receptionist")
    assert response.status_code == 403


def test_summary_dependency_fails_closed_for_non_mock_provider(monkeypatch):
    monkeypatch.setattr(settings, "SUMMARY_WORKFLOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "external-provider")
    with pytest.raises(HTTPException) as error:
        _require_enabled()
    assert error.value.status_code == 503
