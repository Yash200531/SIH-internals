from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.token import create_dev_token
from app.main import app
from app.search.audit import InMemoryClinicalSearchAuditRepository
from app.search.contracts import (
    ClinicalSearchHit,
    ClinicalSearchRecord,
    ClinicalSearchResponse,
    SearchFacets,
    SourceKind,
)
from app.search.dependencies import get_clinical_search_service
from app.search.service import ClinicalSearchService

client = TestClient(app)


class _Store:
    def __init__(self) -> None:
        self.calls = []
        self.fail = False

    async def search(self, criteria):
        self.calls.append(criteria)
        if self.fail:
            raise RuntimeError("backend details must not leak")
        source_id = uuid4()
        return ClinicalSearchResponse(
            total=1,
            hits=[
                ClinicalSearchHit(
                    record_id=f"summary:{source_id}",
                    facility_id=criteria.facility_ids[0],
                    patient_id=criteria.patient_id,
                    encounter_id=uuid4(),
                    source_kind=SourceKind.SIGNED_SUMMARY,
                    source_id=source_id,
                    title="=reviewed discharge summary",
                    occurred_at=datetime.now(UTC),
                )
            ],
            facets=SearchFacets(source_kinds={"signed_summary": 1}),
            took_ms=3,
        )


class _Canonical:
    def __init__(self) -> None:
        self.records: list[ClinicalSearchRecord] = []

    async def list_patient_records(self, **kwargs):
        return [
            record
            for record in self.records
            if record.patient_id == kwargs["patient_id"]
            and record.facility_id in kwargs["facility_ids"]
            and (kwargs.get("source_kind") is None or record.source_kind == kwargs["source_kind"])
            and (kwargs.get("entity_type") is None or record.entity_type == kwargs["entity_type"])
        ]


@pytest.fixture
def search_service():
    store = _Store()
    canonical = _Canonical()
    audit = InMemoryClinicalSearchAuditRepository()
    service = ClinicalSearchService(store, canonical, audit)
    app.dependency_overrides[get_clinical_search_service] = lambda: service
    yield store, canonical, audit
    app.dependency_overrides.pop(get_clinical_search_service, None)


def _headers(
    role: str,
    tenant_id: UUID,
    facility_id: UUID,
    *,
    user_id: UUID | None = None,
) -> dict[str, str]:
    token = create_dev_token(
        str(user_id or uuid4()),
        None,
        role,
        str(tenant_id),
        [str(facility_id)],
    )
    return {"Authorization": f"Bearer {token}"}


def _record(
    tenant_id: UUID,
    patient_id: UUID,
    facility_id: UUID,
    *,
    fact: bool = False,
) -> ClinicalSearchRecord:
    source_id = uuid4()
    return ClinicalSearchRecord(
        record_id=f"{'fact' if fact else 'summary'}:{source_id}",
        tenant_id=tenant_id,
        facility_id=facility_id,
        patient_id=patient_id,
        encounter_id=uuid4(),
        document_id=uuid4() if fact else None,
        source_kind=SourceKind.REVIEWED_FACT if fact else SourceKind.SIGNED_SUMMARY,
        source_id=source_id,
        title="Medication" if fact else "Signed report",
        content="Metformin 500 mg" if fact else "Reviewed myocardial infarction",
        entity_type="medication_statement" if fact else None,
        statement_status="document_stated" if fact else None,
        occurred_at=datetime.now(UTC),
        security_labels=["human-reviewed", "restricted"],
    )


def test_doctor_search_is_token_scoped_audited_and_correlated(search_service) -> None:
    store, _canonical, audit = search_service
    tenant_id, facility_id, patient_id = uuid4(), uuid4(), uuid4()
    response = client.get(
        "/api/v1/clinical-search",
        params={
            "purpose": "treatment",
            "patient_id": str(patient_id),
            "q": "heart attack",
        },
        headers=_headers("doctor", tenant_id, facility_id),
    )

    assert response.status_code == 200
    assert UUID(response.headers["X-Correlation-ID"])
    assert store.calls[0].tenant_id == tenant_id
    assert store.calls[0].patient_id == patient_id
    assert store.calls[0].facility_ids == (facility_id,)
    assert audit.entries[0].outcome == "success"
    assert "heart attack" not in str(audit.entries[0].model_dump())


def test_patient_search_ignores_client_patient_id_and_admin_is_denied(search_service) -> None:
    store, _canonical, _audit = search_service
    tenant_id, facility_id, patient_id = uuid4(), uuid4(), uuid4()
    patient = client.get(
        "/api/v1/clinical-search",
        params={
            "purpose": "treatment",
            "patient_id": str(uuid4()),
            "q": "reviewed",
        },
        headers=_headers(
            "patient", tenant_id, facility_id, user_id=patient_id
        ),
    )
    admin = client.get(
        "/api/v1/clinical-search",
        params={"purpose": "treatment", "patient_id": str(patient_id)},
        headers=_headers("admin", tenant_id, facility_id),
    )

    assert patient.status_code == 200
    assert store.calls[0].patient_id == patient_id
    assert admin.status_code == 403


def test_facility_escape_and_nurse_export_are_denied(search_service) -> None:
    tenant_id, allowed, denied, patient_id = uuid4(), uuid4(), uuid4(), uuid4()
    escaped = client.get(
        "/api/v1/clinical-search",
        params={
            "purpose": "treatment",
            "patient_id": str(patient_id),
            "facility_id": str(denied),
        },
        headers=_headers("doctor", tenant_id, allowed),
    )
    export = client.get(
        "/api/v1/clinical-search/export.csv",
        params={"purpose": "treatment", "patient_id": str(patient_id)},
        headers=_headers("nurse", tenant_id, allowed),
    )

    assert escaped.status_code == 403
    assert export.status_code == 403


def test_doctor_csv_export_is_private_and_formula_safe(search_service) -> None:
    tenant_id, facility_id, patient_id = uuid4(), uuid4(), uuid4()
    response = client.get(
        "/api/v1/clinical-search/export.csv",
        params={"purpose": "treatment", "patient_id": str(patient_id)},
        headers=_headers("doctor", tenant_id, facility_id),
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "'=reviewed discharge summary" in response.text


def test_staff_and_patient_longitudinal_routes_use_canonical_scope(search_service) -> None:
    _store, canonical, audit = search_service
    tenant_id, facility_id, patient_id = uuid4(), uuid4(), uuid4()
    canonical.records = [_record(tenant_id, patient_id, facility_id)]
    staff = client.get(
        f"/api/v1/clinical-search/timeline/{patient_id}",
        params={"purpose": "treatment"},
        headers=_headers("nurse", tenant_id, facility_id),
    )
    patient = client.get(
        "/api/v1/patient-portal/me/longitudinal-timeline",
        params={"purpose": "treatment"},
        headers=_headers("patient", tenant_id, facility_id, user_id=patient_id),
    )

    assert staff.status_code == 200
    assert staff.json()["summary"]["total_events"] == 1
    assert patient.status_code == 200
    assert patient.json()["patient_id"] == str(patient_id)
    assert [entry.action for entry in audit.entries] == ["timeline", "timeline"]


def test_fhir_document_reference_basic_and_operation_outcomes(search_service) -> None:
    _store, canonical, _audit = search_service
    tenant_id, facility_id, patient_id = uuid4(), uuid4(), uuid4()
    canonical.records = [
        _record(tenant_id, patient_id, facility_id),
        _record(tenant_id, patient_id, facility_id, fact=True),
    ]
    headers = _headers("doctor", tenant_id, facility_id)
    common = {"purpose": "treatment", "patient": str(patient_id)}
    documents = client.get(
        "/api/v1/fhir-search/DocumentReference", params=common, headers=headers
    )
    facts = client.get(
        "/api/v1/fhir-search/Basic",
        params={**common, "code": "medication_statement"},
        headers=headers,
    )
    unsupported = client.get(
        "/api/v1/fhir-search/Condition", params=common, headers=headers
    )
    bad_parameter = client.get(
        "/api/v1/fhir-search/Basic",
        params={**common, "status": "active"},
        headers=headers,
    )

    assert documents.status_code == 200
    assert documents.json()["type"] == "searchset"
    assert documents.json()["entry"][0]["resource"]["resourceType"] == "DocumentReference"
    assert facts.status_code == 200
    assert facts.json()["entry"][0]["resource"]["resourceType"] == "Basic"
    assert unsupported.status_code == 400
    assert unsupported.json()["resourceType"] == "OperationOutcome"
    assert bad_parameter.status_code == 400
    assert bad_parameter.json()["resourceType"] == "OperationOutcome"


def test_backend_details_do_not_leak_on_search_failure(search_service) -> None:
    store, _canonical, audit = search_service
    store.fail = True
    tenant_id, facility_id, patient_id = uuid4(), uuid4(), uuid4()
    response = client.get(
        "/api/v1/clinical-search",
        params={"purpose": "treatment", "patient_id": str(patient_id), "q": "private"},
        headers=_headers("doctor", tenant_id, facility_id),
    )

    assert response.status_code == 503
    assert "backend details" not in response.text
    assert audit.entries[0].outcome == "unavailable"


def test_invalid_cursor_is_rejected_before_the_search_backend(search_service) -> None:
    store, _canonical, _audit = search_service
    tenant_id, facility_id, patient_id = uuid4(), uuid4(), uuid4()

    response = client.get(
        "/api/v1/clinical-search",
        params={
            "purpose": "treatment",
            "patient_id": str(patient_id),
            "cursor": "not-an-opaque-cursor",
        },
        headers=_headers("doctor", tenant_id, facility_id),
    )

    assert response.status_code == 422
    assert store.calls == []


def test_unauthorized_response_still_has_a_correlation_id(search_service) -> None:
    response = client.get(
        "/api/v1/clinical-search",
        params={"purpose": "treatment", "patient_id": str(uuid4())},
    )

    assert response.status_code == 401
    assert UUID(response.headers["X-Correlation-ID"])
