from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.token import create_dev_token
from app.documents.authorization import DocumentPurposeAuthorizer
from app.documents.dependencies import (
    get_document_purpose_authorizer,
    get_document_repository,
    get_document_store,
)
from app.documents.promotion import DocumentTimelineEntry
from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.documents.repository import DocumentCreateResult, DocumentNotFound
from app.documents.storage import UploadGrant, VerifiedUpload, quarantine_object_key
from app.llm.schemas import EvidenceLink, OutputConfidence
from app.main import app
from app.patient_portal.consent_repository import InMemoryPatientConsentRepository
from app.patient_portal.dependencies import (
    get_patient_consent_repository,
    get_patient_intake_repository,
    get_patient_portal_service,
)
from app.patient_portal.intake_repository import InMemoryPatientIntakeRepository
from app.patient_portal.service import PatientPortalService
from app.summary_workflow.contracts import (
    SummaryAction,
    SummaryContent,
    SummaryRecord,
    SummaryStatus,
)
from app.summary_workflow.repository import InMemorySummaryRepository

client = TestClient(app)


class DocumentRepositoryStub:
    def __init__(self) -> None:
        self.records: dict[tuple[UUID, UUID], DocumentRegistryEntry] = {}

    async def create(self, document: DocumentRegistryEntry) -> DocumentCreateResult:
        self.records[(document.tenant_id, document.id)] = document.model_copy(deep=True)
        return DocumentCreateResult(document=document.model_copy(deep=True), created=True)

    async def get(self, tenant_id: UUID, document_id: UUID) -> DocumentRegistryEntry:
        record = self.records.get((tenant_id, document_id))
        if record is None:
            raise DocumentNotFound("Document not found")
        return record.model_copy(deep=True)

    async def list_for_patient(
        self,
        *,
        tenant_id: UUID,
        patient_id: UUID,
        facility_ids: set[UUID],
        limit: int = 100,
    ) -> list[DocumentRegistryEntry]:
        return [
            item.model_copy(deep=True)
            for (record_tenant, _), item in self.records.items()
            if record_tenant == tenant_id
            and item.patient_id == patient_id
            and item.facility_id in facility_ids
        ][:limit]

    async def finalize_upload(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        expected_version: int,
        object_key: str,
        checksum_sha256: str,
        detected_mime: str,
    ) -> DocumentRegistryEntry:
        record = await self.get(tenant_id, document_id)
        record.attach_upload(
            object_key=object_key,
            checksum_sha256=checksum_sha256,
            detected_mime=detected_mime,
            expected_version=expected_version,
        )
        record.transition(DocumentState.QUARANTINED, expected_version=record.version)
        self.records[(tenant_id, document_id)] = record.model_copy(deep=True)
        return record

    async def cancel(
        self, *, tenant_id: UUID, document_id: UUID, expected_version: int
    ) -> DocumentRegistryEntry:
        record = await self.get(tenant_id, document_id)
        record.transition(DocumentState.CANCELLED, expected_version=expected_version)
        self.records[(tenant_id, document_id)] = record.model_copy(deep=True)
        return record


class AllowingAuthorizer(DocumentPurposeAuthorizer):
    async def authorize(self, **_kwargs) -> None:
        return None


class DocumentStoreStub:
    async def create_upload_grant(self, document: DocumentRegistryEntry) -> UploadGrant:
        return UploadGrant(
            url=f"https://objects.test/{document.id}",
            object_key=quarantine_object_key(document),
            expires_in_seconds=300,
            required_headers={"Content-Type": document.declared_mime},
        )

    async def verify_upload(
        self, document: DocumentRegistryEntry, object_key: str
    ) -> VerifiedUpload:
        return VerifiedUpload(
            object_key=object_key,
            size_bytes=document.declared_size_bytes,
            checksum_sha256="c" * 64,
            detected_mime=document.declared_mime,
        )


class TimelineStub:
    def __init__(self, entries: list[DocumentTimelineEntry] | None = None) -> None:
        self.entries = entries or []

    async def list_timeline(
        self,
        *,
        tenant_id: UUID,
        patient_id: UUID,
        facility_ids: set[UUID],
        limit: int = 100,
    ) -> list[DocumentTimelineEntry]:
        return [
            entry
            for entry in self.entries
            if entry.patient_id == patient_id
        ][:limit]

    async def count_timeline(
        self,
        *,
        tenant_id: UUID,
        patient_id: UUID,
        facility_ids: set[UUID],
    ) -> int:
        return sum(1 for entry in self.entries if entry.patient_id == patient_id)


@pytest.fixture
def portal():
    summaries = InMemorySummaryRepository()
    timeline = TimelineStub()
    service = PatientPortalService(summaries, timeline)
    app.dependency_overrides[get_patient_portal_service] = lambda: service
    yield summaries, timeline
    app.dependency_overrides.pop(get_patient_portal_service, None)


@pytest.fixture
def patient_documents():
    repository = DocumentRepositoryStub()
    app.dependency_overrides[get_document_repository] = lambda: repository
    app.dependency_overrides[get_document_purpose_authorizer] = lambda: AllowingAuthorizer()
    app.dependency_overrides[get_document_store] = lambda: DocumentStoreStub()
    yield repository
    for dependency in (
        get_document_repository,
        get_document_purpose_authorizer,
        get_document_store,
    ):
        app.dependency_overrides.pop(dependency, None)


@pytest.fixture
def patient_consents():
    repository = InMemoryPatientConsentRepository()
    app.dependency_overrides[get_patient_consent_repository] = lambda: repository
    yield repository
    app.dependency_overrides.pop(get_patient_consent_repository, None)


@pytest.fixture
def patient_intakes():
    repository = InMemoryPatientIntakeRepository()
    app.dependency_overrides[get_patient_intake_repository] = lambda: repository
    yield repository
    app.dependency_overrides.pop(get_patient_intake_repository, None)


def _headers(
    patient_id: UUID,
    tenant_id: UUID,
    facility_id: UUID,
    *,
    role: str = "patient",
) -> dict[str, str]:
    token = create_dev_token(
        str(patient_id),
        "patient@example.test",
        role,
        str(tenant_id),
        [str(facility_id)],
    )
    return {"Authorization": f"Bearer {token}"}


def _record(
    *,
    tenant_id: UUID,
    facility_id: UUID,
    patient_id: UUID,
    status: SummaryStatus = SummaryStatus.SIGNED,
) -> SummaryRecord:
    now = datetime.now(UTC)
    signed = status is SummaryStatus.SIGNED
    return SummaryRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        facility_id=facility_id,
        patient_id=patient_id,
        encounter_id=uuid4(),
        lineage_id=uuid4(),
        generation=1,
        status=status,
        content=SummaryContent(
            chief_complaint="Chest discomfort",
            history_of_present_illness=["Started this morning"],
            relevant_negatives=["No fainting reported"],
            document_facts=["Prescription reviewed"],
            red_flags=["Seek staff help if breathing worsens"],
            uncertainties=["Duration needs confirmation"],
        ),
        evidence=[
            EvidenceLink(
                output_path="history_of_present_illness[0]",
                source_path="confirmed_answers.onset",
                source_type="patient_response",
            )
        ],
        confidence=OutputConfidence(
            score=0.8,
            basis="structured_completeness",
            not_clinical_probability=True,
        ),
        provider="mock",
        degraded=False,
        lock_version=4 if signed else 1,
        created_by_actor_id=uuid4(),
        created_at=now,
        updated_at=now,
        signed_by_actor_id=uuid4() if signed else None,
        signed_at=now if signed else None,
        signature_sha256="a" * 64 if signed else None,
        request_hash_sha256="b" * 64,
    )


async def _store(repository: InMemorySummaryRepository, record: SummaryRecord) -> None:
    action = SummaryAction(
        id=uuid4(),
        tenant_id=record.tenant_id,
        summary_id=record.id,
        actor_id=record.created_by_actor_id,
        actor_role="doctor",
        action="signed" if record.status is SummaryStatus.SIGNED else "generated",
        from_status=SummaryStatus.IN_REVIEW if record.status is SummaryStatus.SIGNED else None,
        to_status=record.status,
        resulting_lock_version=record.lock_version,
        occurred_at=record.updated_at,
    )
    await repository.create(
        record=record,
        action=action,
        idempotency_key=f"test-{record.id}",
        request_hash_sha256=record.request_hash_sha256,
    )


@pytest.mark.asyncio
async def test_patient_lists_only_own_signed_reports(portal) -> None:
    repository, _timeline = portal
    tenant_id, facility_id, patient_id = uuid4(), uuid4(), uuid4()
    own_signed = _record(
        tenant_id=tenant_id, facility_id=facility_id, patient_id=patient_id
    )
    own_draft = _record(
        tenant_id=tenant_id,
        facility_id=facility_id,
        patient_id=patient_id,
        status=SummaryStatus.DRAFT,
    )
    other_patient = _record(
        tenant_id=tenant_id, facility_id=facility_id, patient_id=uuid4()
    )
    wrong_facility = _record(
        tenant_id=tenant_id, facility_id=uuid4(), patient_id=patient_id
    )
    for record in (own_signed, own_draft, other_patient, wrong_facility):
        await _store(repository, record)

    response = client.get(
        "/api/v1/patient-portal/me/reports",
        headers=_headers(patient_id, tenant_id, facility_id),
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(own_signed.id)]


@pytest.mark.asyncio
async def test_patient_views_and_downloads_complete_signed_report(portal) -> None:
    repository, _timeline = portal
    tenant_id, facility_id, patient_id = uuid4(), uuid4(), uuid4()
    report = _record(
        tenant_id=tenant_id, facility_id=facility_id, patient_id=patient_id
    )
    await _store(repository, report)
    headers = _headers(patient_id, tenant_id, facility_id)

    detail = client.get(
        f"/api/v1/patient-portal/me/reports/{report.id}", headers=headers
    )
    download = client.get(
        f"/api/v1/patient-portal/me/reports/{report.id}/download", headers=headers
    )

    assert detail.status_code == 200
    assert detail.json()["content"]["history_of_present_illness"] == [
        "Started this morning"
    ]
    assert detail.json()["evidence"][0]["source_type"] == "patient_response"
    assert download.status_code == 200
    assert download.headers["cache-control"] == "private, no-store"
    assert "attachment;" in download.headers["content-disposition"]
    assert "Integrity SHA-256: " + "a" * 64 in download.text
    assert "Started this morning" in download.text


@pytest.mark.asyncio
async def test_patient_cannot_read_other_patient_or_unsigned_report(portal) -> None:
    repository, _timeline = portal
    tenant_id, facility_id, patient_id = uuid4(), uuid4(), uuid4()
    other = _record(
        tenant_id=tenant_id, facility_id=facility_id, patient_id=uuid4()
    )
    draft = _record(
        tenant_id=tenant_id,
        facility_id=facility_id,
        patient_id=patient_id,
        status=SummaryStatus.DRAFT,
    )
    await _store(repository, other)
    await _store(repository, draft)
    headers = _headers(patient_id, tenant_id, facility_id)

    assert client.get(
        f"/api/v1/patient-portal/me/reports/{other.id}", headers=headers
    ).status_code == 404
    assert client.get(
        f"/api/v1/patient-portal/me/reports/{draft.id}", headers=headers
    ).status_code == 404


def test_patient_portal_rejects_staff_and_invalid_patient_identity(portal) -> None:
    tenant_id, facility_id, patient_id = uuid4(), uuid4(), uuid4()
    denied = client.get(
        "/api/v1/patient-portal/me/reports",
        headers=_headers(patient_id, tenant_id, facility_id, role="doctor"),
    )
    malformed = create_dev_token(
        "not-a-uuid", "patient@example.test", "patient", str(tenant_id), [str(facility_id)]
    )
    invalid = client.get(
        "/api/v1/patient-portal/me/reports",
        headers={"Authorization": f"Bearer {malformed}"},
    )
    assert denied.status_code == 403
    assert invalid.status_code == 403


@pytest.mark.asyncio
async def test_dashboard_includes_reviewed_timeline_without_raw_ocr(portal) -> None:
    repository, timeline = portal
    tenant_id, facility_id, patient_id = uuid4(), uuid4(), uuid4()
    report = _record(
        tenant_id=tenant_id, facility_id=facility_id, patient_id=patient_id
    )
    await _store(repository, report)
    timeline.entries.append(
        DocumentTimelineEntry(
            id=uuid4(),
            patient_id=patient_id,
            encounter_id=report.encounter_id,
            document_id=uuid4(),
            fact_id=uuid4(),
            event_type="medication",
            display_value="Reviewed medicine entry",
            unit=None,
            statement_status="document_stated",
            occurred_at=datetime.now(UTC),
        )
    )

    response = client.get(
        "/api/v1/patient-portal/me/dashboard",
        headers=_headers(patient_id, tenant_id, facility_id),
    )

    assert response.status_code == 200
    assert response.json()["signed_report_count"] == 1
    assert response.json()["reviewed_timeline_count"] == 1
    assert "ocr" not in response.text.lower()


@pytest.mark.asyncio
async def test_dashboard_counts_are_not_truncated_to_recent_items(portal) -> None:
    repository, timeline = portal
    tenant_id, facility_id, patient_id = uuid4(), uuid4(), uuid4()
    for _ in range(101):
        report = _record(
            tenant_id=tenant_id, facility_id=facility_id, patient_id=patient_id
        )
        await _store(repository, report)
        timeline.entries.append(
            DocumentTimelineEntry(
                id=uuid4(),
                patient_id=patient_id,
                encounter_id=report.encounter_id,
                document_id=uuid4(),
                fact_id=uuid4(),
                event_type="medication",
                display_value="Reviewed medicine entry",
                unit=None,
                statement_status="document_stated",
                occurred_at=datetime.now(UTC),
            )
        )

    response = client.get(
        "/api/v1/patient-portal/me/dashboard",
        headers=_headers(patient_id, tenant_id, facility_id),
    )

    assert response.status_code == 200
    assert response.json()["signed_report_count"] == 101
    assert response.json()["reviewed_timeline_count"] == 101
    assert len(response.json()["recent_reports"]) == 3
    assert len(response.json()["recent_timeline"]) == 5


def test_patient_upload_uses_self_identity_and_existing_document_lifecycle(
    patient_documents,
) -> None:
    tenant_id, facility_id, patient_id, encounter_id = (
        uuid4() for _ in range(4)
    )
    headers = _headers(patient_id, tenant_id, facility_id)
    headers["Idempotency-Key"] = "patient-prescription-1"
    created = client.post(
        "/api/v1/patient-portal/me/documents",
        headers=headers,
        json={
            "facility_id": str(facility_id),
            "encounter_id": str(encounter_id),
            "consent_reference": str(uuid4()),
            "original_filename": "prescription.pdf",
            "declared_mime": "application/pdf",
            "declared_size_bytes": 1024,
        },
    )
    assert created.status_code == 201
    document = created.json()
    assert document["patient_id"] == str(patient_id)
    assert document["state"] == "initiated"

    grant = client.post(
        f"/api/v1/patient-portal/me/documents/{document['id']}/upload-session",
        headers=headers,
    )
    assert grant.status_code == 200
    assert grant.json()["required_headers"] == {"Content-Type": "application/pdf"}

    finalized = client.post(
        f"/api/v1/patient-portal/me/documents/{document['id']}/finalize",
        headers=headers,
        json={"expected_version": document["version"]},
    )
    assert finalized.status_code == 200
    assert finalized.json()["state"] == "quarantined"
    assert finalized.json()["version"] == 3

    listed = client.get(
        "/api/v1/patient-portal/me/documents", headers=headers
    )
    assert [item["id"] for item in listed.json()] == [document["id"]]


def test_patient_upload_rejects_wrong_patient_and_unsupported_type(
    patient_documents,
) -> None:
    tenant_id, facility_id, patient_id, encounter_id = (
        uuid4() for _ in range(4)
    )
    headers = _headers(patient_id, tenant_id, facility_id)
    headers["Idempotency-Key"] = "patient-prescription-2"
    unsupported = client.post(
        "/api/v1/patient-portal/me/documents",
        headers=headers,
        json={
            "facility_id": str(facility_id),
            "encounter_id": str(encounter_id),
            "consent_reference": str(uuid4()),
            "original_filename": "notes.txt",
            "declared_mime": "text/plain",
            "declared_size_bytes": 10,
        },
    )
    assert unsupported.status_code == 422

    valid = client.post(
        "/api/v1/patient-portal/me/documents",
        headers={**headers, "Idempotency-Key": "patient-prescription-3"},
        json={
            "facility_id": str(facility_id),
            "encounter_id": str(encounter_id),
            "consent_reference": str(uuid4()),
            "original_filename": "rx.png",
            "declared_mime": "image/png",
            "declared_size_bytes": 128,
        },
    )
    other_headers = _headers(uuid4(), tenant_id, facility_id)
    hidden = client.get(
        f"/api/v1/patient-portal/me/documents/{valid.json()['id']}",
        headers=other_headers,
    )
    assert hidden.status_code == 404


def test_patient_can_grant_list_and_revoke_own_consent(patient_consents) -> None:
    tenant_id, facility_id, patient_id, encounter_id = (
        uuid4() for _ in range(4)
    )
    headers = _headers(patient_id, tenant_id, facility_id)
    granted = client.post(
        "/api/v1/patient-portal/me/consents",
        headers=headers,
        json={
            "encounter_id": str(encounter_id),
            "document_upload": True,
            "retain_audio": False,
            "expires_in_hours": 24,
        },
    )
    assert granted.status_code == 201
    assert granted.json()["patient_id"] == str(patient_id)
    assert granted.json()["scope"] == {
        "document_upload": True,
        "audio_retention": False,
    }

    listed = client.get(
        "/api/v1/patient-portal/me/consents", headers=headers
    )
    assert [item["id"] for item in listed.json()] == [granted.json()["id"]]

    revoked = client.post(
        f"/api/v1/patient-portal/me/consents/{granted.json()['id']}/revoke",
        headers=headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert revoked.json()["version"] == 2


def test_patient_cannot_revoke_another_patients_consent(patient_consents) -> None:
    tenant_id, facility_id, owner_id, other_id = (
        uuid4() for _ in range(4)
    )
    granted = client.post(
        "/api/v1/patient-portal/me/consents",
        headers=_headers(owner_id, tenant_id, facility_id),
        json={"encounter_id": str(uuid4())},
    )
    response = client.post(
        f"/api/v1/patient-portal/me/consents/{granted.json()['id']}/revoke",
        headers=_headers(other_id, tenant_id, facility_id),
    )
    assert response.status_code == 404


def test_confirmed_patient_intake_is_persisted_idempotently(patient_intakes) -> None:
    tenant_id, facility_id, patient_id = uuid4(), uuid4(), uuid4()
    headers = _headers(patient_id, tenant_id, facility_id)
    headers["Idempotency-Key"] = "confirmed-intake-1"
    body = {
        "facility_id": str(facility_id),
        "encounter_id": str(uuid4()),
        "session_id": str(uuid4()),
        "consent_id": str(uuid4()),
        "language": "hi",
        "chief_complaint": "सीने में दर्द",
        "confirmed_answers": {"site": "सीना", "onset": "आज"},
        "summary_draft": {
            "chief_complaint": "सीने में दर्द",
            "history_of_present_illness": ["दर्द आज शुरू हुआ"],
            "relevant_negatives": [],
            "document_facts": [],
            "red_flags": ["RF-CARD-001"],
            "uncertainties": ["अवधि की पुष्टि करें"],
        },
        "decision": "accepted",
        "provider": "mock",
    }

    first = client.post(
        "/api/v1/patient-portal/me/intakes", headers=headers, json=body
    )
    replay = client.post(
        "/api/v1/patient-portal/me/intakes", headers=headers, json=body
    )

    assert first.status_code == replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"]
    assert first.json()["patient_id"] == str(patient_id)
    assert first.json()["decision"] == "accepted"


def test_patient_intake_idempotency_rejects_changed_decision(patient_intakes) -> None:
    tenant_id, facility_id, patient_id = uuid4(), uuid4(), uuid4()
    headers = _headers(patient_id, tenant_id, facility_id)
    headers["Idempotency-Key"] = "confirmed-intake-2"
    body = {
        "facility_id": str(facility_id),
        "encounter_id": str(uuid4()),
        "session_id": str(uuid4()),
        "consent_id": str(uuid4()),
        "language": "en",
        "chief_complaint": "Headache",
        "confirmed_answers": {},
        "summary_draft": {
            "chief_complaint": "Headache",
            "history_of_present_illness": ["Headache reported"],
            "relevant_negatives": [],
            "document_facts": [],
            "red_flags": [],
            "uncertainties": [],
        },
        "decision": "accepted",
        "provider": "mock",
    }
    assert client.post(
        "/api/v1/patient-portal/me/intakes", headers=headers, json=body
    ).status_code == 201
    body["decision"] = "rejected"
    assert client.post(
        "/api/v1/patient-portal/me/intakes", headers=headers, json=body
    ).status_code == 409
