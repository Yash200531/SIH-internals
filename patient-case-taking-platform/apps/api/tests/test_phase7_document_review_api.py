"""HTTP authorization and failure semantics for clinical document review."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.token import create_dev_token
from app.documents.dependencies import (
    get_document_review_repository,
    get_document_store,
)
from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.documents.review import (
    CandidateDecision,
    ReviewCandidate,
    ReviewConflict,
    ReviewDocument,
    ReviewIncomplete,
    ReviewQueueItem,
    ReviewState,
)
from app.documents.storage import ObjectVerificationError, PageArtifact, PreviewGrant
from app.main import app

client = TestClient(app)


def _candidate() -> ReviewCandidate:
    return ReviewCandidate(
        candidate_id=uuid4(),
        entity_type="medication_statement",
        normalized_value="Metformin",
        unit=None,
        source_page_artifact_id=uuid4(),
        source_ocr_artifact_id=uuid4(),
        source_region_id=uuid4(),
        source_page_number=1,
        parser_signal="prescription.medication.v1",
        negated=False,
        temporality="document_unspecified",
        subject="patient",
        uncertainty=None,
        document_statement=True,
        clinician_confirmed_current=False,
        review_state=ReviewState.UNREVIEWED,
        version=1,
    )


class _ReviewRepository:
    def __init__(self) -> None:
        self.tenant_id = uuid4()
        self.facility_id = uuid4()
        self.document_id = uuid4()
        self.patient_id = uuid4()
        self.encounter_id = uuid4()
        self.candidate = _candidate()
        self.review = ReviewDocument(
            document_id=self.document_id,
            tenant_id=self.tenant_id,
            facility_id=self.facility_id,
            patient_id=self.patient_id,
            encounter_id=self.encounter_id,
            purpose="treatment",
            document_class="prescription",
            state="review_required",
            version=8,
            updated_at=datetime.now(UTC),
            candidates=(self.candidate,),
        )
        self.decision_error: Exception | None = None
        self.finalize_error: Exception | None = None

    async def list_queue(self, **_scope: object) -> list[ReviewQueueItem]:
        return [
            ReviewQueueItem(
                document_id=self.document_id,
                facility_id=self.facility_id,
                patient_id=self.patient_id,
                encounter_id=self.encounter_id,
                document_class="prescription",
                state="review_required",
                version=8,
                updated_at=self.review.updated_at,
                candidate_count=1,
                unresolved_count=1,
            )
        ]

    async def get(self, **_scope: object) -> ReviewDocument:
        return self.review

    async def get_registry(self, **_scope: object) -> DocumentRegistryEntry:
        return DocumentRegistryEntry(
            id=self.document_id,
            tenant_id=self.tenant_id,
            facility_id=self.facility_id,
            patient_id=self.patient_id,
            encounter_id=self.encounter_id,
            uploader_actor_id=uuid4(),
            purpose="treatment",
            consent_reference="consent/test",
            original_filename="hidden.png",
            declared_document_class="prescription",
            declared_mime="image/png",
            declared_size_bytes=10,
            idempotency_key="review-api-test",
            state=DocumentState.REVIEW_REQUIRED,
        )

    async def get_page(self, **_scope: object) -> PageArtifact:
        return PageArtifact(
            id=self.candidate.source_page_artifact_id,
            page_number=1,
            object_key=(
                f"derived/{self.tenant_id}/{self.document_id}/run/pages/0001.png"
            ),
            checksum_sha256="a" * 64,
            mime="image/png",
            width=1200,
            height=1600,
            preprocessing_version="normalize.v1",
        )

    async def decide(self, *, decision: CandidateDecision, **_scope: object) -> ReviewCandidate:
        if self.decision_error:
            raise self.decision_error
        state = decision.validate()
        self.candidate = ReviewCandidate(
            **{
                **self.candidate.__dict__,
                "review_state": state,
                "version": self.candidate.version + 1,
                "normalized_value": decision.corrected_value
                if decision.corrected_value is not None
                else self.candidate.normalized_value,
            }
        )
        return self.candidate

    async def add_manual_candidate(self, *, candidate, **_scope: object) -> ReviewCandidate:
        candidate.validate()
        return ReviewCandidate(
            **{
                **self.candidate.__dict__,
                "candidate_id": uuid4(),
                "entity_type": candidate.entity_type,
                "normalized_value": candidate.normalized_value,
                "unit": candidate.unit,
                "source_page_artifact_id": candidate.source_page_artifact_id,
                "source_page_number": candidate.source_page_number,
                "source_ocr_artifact_id": None,
                "source_region_id": None,
                "review_state": ReviewState.CORRECTED,
                "version": 2,
            }
        )

    async def open_manual_review(self, **_scope: object) -> ReviewDocument:
        return self.review

    async def finalize(self, **_scope: object) -> ReviewDocument:
        if self.finalize_error:
            raise self.finalize_error
        return ReviewDocument(
            **{**self.review.__dict__, "state": "reviewed", "version": 9}
        )


class _PreviewStore:
    def __init__(self) -> None:
        self.error: Exception | None = None

    async def create_page_preview_grant(
        self, _document: DocumentRegistryEntry, _page: PageArtifact
    ) -> PreviewGrant:
        if self.error:
            raise self.error
        return PreviewGrant("https://object-store.invalid/review-page", 300)


@pytest.fixture
def review_repository() -> _ReviewRepository:
    repository = _ReviewRepository()
    app.dependency_overrides[get_document_review_repository] = lambda: repository
    yield repository
    app.dependency_overrides.pop(get_document_review_repository, None)


@pytest.fixture
def preview_store() -> _PreviewStore:
    store = _PreviewStore()
    app.dependency_overrides[get_document_store] = lambda: store
    yield store
    app.dependency_overrides.pop(get_document_store, None)


def _headers(repository: _ReviewRepository, role: str = "nurse") -> dict[str, str]:
    token = create_dev_token(
        str(uuid4()),
        "reviewer@example.test",
        role,
        str(repository.tenant_id),
        [str(repository.facility_id)],
    )
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": "review-1"}


def test_queue_is_available_to_nurse_and_excludes_source_text(
    review_repository: _ReviewRepository,
) -> None:
    response = client.get(
        "/api/v1/document-reviews",
        headers=_headers(review_repository),
    )

    assert response.status_code == 200
    assert response.json()[0]["unresolved_count"] == 1
    assert "Metformin" not in response.text


def test_queue_rejects_non_clinical_role(review_repository: _ReviewRepository) -> None:
    response = client.get(
        "/api/v1/document-reviews",
        headers=_headers(review_repository, role="receptionist"),
    )

    assert response.status_code == 403


def test_accept_requires_source_verification(review_repository: _ReviewRepository) -> None:
    response = client.post(
        (
            f"/api/v1/document-reviews/{review_repository.document_id}/candidates/"
            f"{review_repository.candidate.candidate_id}/decisions"
        ),
        headers=_headers(review_repository),
        json={"action": "accept", "expected_candidate_version": 1},
    )

    assert response.status_code == 422
    assert "Source verification" in response.json()["detail"]


def test_stale_candidate_is_a_conflict(review_repository: _ReviewRepository) -> None:
    review_repository.decision_error = ReviewConflict("Candidate version is stale")
    response = client.post(
        (
            f"/api/v1/document-reviews/{review_repository.document_id}/candidates/"
            f"{review_repository.candidate.candidate_id}/decisions"
        ),
        headers=_headers(review_repository),
        json={
            "action": "accept",
            "expected_candidate_version": 1,
            "source_verified": True,
        },
    )

    assert response.status_code == 409


def test_partial_review_cannot_be_finalized(review_repository: _ReviewRepository) -> None:
    review_repository.finalize_error = ReviewIncomplete("Every candidate must be final")
    response = client.post(
        f"/api/v1/document-reviews/{review_repository.document_id}/finalize",
        headers=_headers(review_repository, role="doctor"),
        json={"expected_document_version": 8},
    )

    assert response.status_code == 422


def test_manual_entry_is_source_linked_and_immediately_reviewed(
    review_repository: _ReviewRepository,
) -> None:
    response = client.post(
        f"/api/v1/document-reviews/{review_repository.document_id}/candidates",
        headers=_headers(review_repository, role="doctor"),
        json={
            "entity_type": "instructions",
            "normalized_value": "after food",
            "source_page_artifact_id": str(
                review_repository.candidate.source_page_artifact_id
            ),
            "source_page_number": 1,
            "source_verified": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["review_state"] == "corrected"
    assert response.json()["source_ocr_artifact_id"] is None


def test_manual_fallback_endpoint_returns_review_workspace(
    review_repository: _ReviewRepository,
) -> None:
    response = client.post(
        f"/api/v1/document-reviews/{review_repository.document_id}/manual",
        headers=_headers(review_repository),
        json={"expected_document_version": 7},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "review_required"


def test_preview_failure_is_actionable_and_does_not_leak_storage_details(
    review_repository: _ReviewRepository,
    preview_store: _PreviewStore,
) -> None:
    preview_store.error = ObjectVerificationError("bucket secret")
    response = client.get(
        (
            f"/api/v1/document-reviews/{review_repository.document_id}/pages/"
            f"{review_repository.candidate.source_page_artifact_id}/preview"
        ),
        headers=_headers(review_repository),
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Source preview is unavailable"}
    assert "bucket secret" not in response.text


def test_preview_uses_a_short_lived_grant(
    review_repository: _ReviewRepository,
    preview_store: _PreviewStore,
) -> None:
    response = client.get(
        (
            f"/api/v1/document-reviews/{review_repository.document_id}/pages/"
            f"{review_repository.candidate.source_page_artifact_id}/preview"
        ),
        headers=_headers(review_repository, role="doctor"),
    )

    assert response.status_code == 200
    assert response.json()["expires_in_seconds"] == 300
