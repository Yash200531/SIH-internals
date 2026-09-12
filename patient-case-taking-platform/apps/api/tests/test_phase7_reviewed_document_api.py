"""Authorization and semantics for reviewed facts and projections."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.token import create_dev_token
from app.documents.dependencies import get_reviewed_fact_repository
from app.documents.promotion import DocumentTimelineEntry, ReviewedDocumentFact
from app.main import app

client = TestClient(app)


class _Repository:
    def __init__(self) -> None:
        self.tenant_id = uuid4()
        self.facility_id = uuid4()
        self.document_id = uuid4()
        self.patient_id = uuid4()
        self.encounter_id = uuid4()
        self.fact_id = uuid4()
        self.fact = ReviewedDocumentFact(
            id=self.fact_id,
            patient_id=self.patient_id,
            encounter_id=self.encounter_id,
            document_id=self.document_id,
            candidate_id=uuid4(),
            entity_type="medication_statement",
            normalized_value="Metformin",
            unit=None,
            source_page_artifact_id=uuid4(),
            source_ocr_artifact_id=uuid4(),
            source_region_id=uuid4(),
            source_page_number=1,
            document_statement=True,
            clinician_confirmed_current=False,
            active=True,
            promoted_at=datetime.now(UTC),
            withdrawn_at=None,
            withdrawal_reason_code=None,
        )
        self.withdraw_calls = 0

    async def list_facts(self, **_scope: object) -> list[ReviewedDocumentFact]:
        return [self.fact]

    async def list_timeline(self, **_scope: object) -> list[DocumentTimelineEntry]:
        return [
            DocumentTimelineEntry(
                id=uuid4(),
                patient_id=self.patient_id,
                encounter_id=self.encounter_id,
                document_id=self.document_id,
                fact_id=self.fact_id,
                event_type="medication_statement",
                display_value="Metformin",
                unit=None,
                statement_status="document_stated",
                occurred_at=self.fact.promoted_at,
            )
        ]

    async def list_fhir_resources(self, **_scope: object) -> list[dict[str, object]]:
        return [
            {
                "resourceType": "Basic",
                "meta": {"tag": [{"code": "document_stated"}]},
            }
        ]

    async def withdraw(self, *, actor_role: str, **_scope: object) -> int:
        if actor_role != "doctor":
            raise PermissionError("Doctor role required to withdraw reviewed facts")
        self.withdraw_calls += 1
        return 1


@pytest.fixture
def repository() -> _Repository:
    value = _Repository()
    app.dependency_overrides[get_reviewed_fact_repository] = lambda: value
    yield value
    app.dependency_overrides.pop(get_reviewed_fact_repository, None)


def _headers(repository: _Repository, role: str = "nurse") -> dict[str, str]:
    token = create_dev_token(
        str(uuid4()),
        "records@example.test",
        role,
        str(repository.tenant_id),
        [str(repository.facility_id)],
    )
    return {"Authorization": f"Bearer {token}"}


def test_reviewed_facts_are_explicitly_document_stated(repository: _Repository) -> None:
    response = client.get(
        f"/api/v1/reviewed-documents/documents/{repository.document_id}/facts",
        headers=_headers(repository),
    )

    assert response.status_code == 200
    assert response.json()[0]["document_statement"] is True
    assert response.json()[0]["clinician_confirmed_current"] is False


def test_timeline_retains_document_statement_status(repository: _Repository) -> None:
    response = client.get(
        f"/api/v1/reviewed-documents/patients/{repository.patient_id}/timeline",
        headers=_headers(repository),
    )

    assert response.status_code == 200
    assert response.json()[0]["statement_status"] == "document_stated"


def test_fhir_projection_does_not_claim_current_medication(repository: _Repository) -> None:
    response = client.get(
        f"/api/v1/reviewed-documents/documents/{repository.document_id}/fhir",
        headers=_headers(repository),
    )

    assert response.status_code == 200
    assert response.json()[0]["resourceType"] == "Basic"
    assert response.json()[0]["meta"]["tag"][0]["code"] == "document_stated"


def test_nurse_cannot_withdraw_reviewed_facts(repository: _Repository) -> None:
    response = client.post(
        f"/api/v1/reviewed-documents/documents/{repository.document_id}/withdraw",
        headers=_headers(repository, role="nurse"),
        json={"reason_code": "entered_in_error"},
    )

    assert response.status_code == 403
    assert repository.withdraw_calls == 0


def test_doctor_withdrawal_is_explicit_and_counted(repository: _Repository) -> None:
    response = client.post(
        f"/api/v1/reviewed-documents/documents/{repository.document_id}/withdraw",
        headers=_headers(repository, role="doctor"),
        json={"reason_code": "entered_in_error"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "document_id": str(repository.document_id),
        "withdrawn_fact_count": 1,
    }
