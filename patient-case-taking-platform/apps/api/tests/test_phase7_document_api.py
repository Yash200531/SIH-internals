"""Authorized Phase 7 document-registration API tests."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.audit.emitter import audit_emitter
from app.auth.token import create_dev_token
from app.documents.authorization import ConsentAuthorizationDenied
from app.documents.dependencies import (
    get_document_purpose_authorizer,
    get_document_repository,
    get_document_store,
)
from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.documents.repository import (
    DocumentCreateResult,
    DocumentNotFound,
    IdempotencyConflict,
)
from app.documents.storage import ObjectVerificationError, UploadGrant, VerifiedUpload
from app.main import app

client = TestClient(app)


class _Repository:
    def __init__(self) -> None:
        self.documents: dict[tuple[UUID, str], DocumentRegistryEntry] = {}
        self.create_calls = 0

    async def create(self, document: DocumentRegistryEntry) -> DocumentCreateResult:
        self.create_calls += 1
        key = (document.tenant_id, document.idempotency_key)
        existing = self.documents.get(key)
        if existing is None:
            self.documents[key] = document
            return DocumentCreateResult(document=document, created=True)
        if existing.original_filename != document.original_filename:
            raise IdempotencyConflict("conflicting registration")
        return DocumentCreateResult(document=existing, created=False)

    async def get(self, tenant_id: UUID, document_id: UUID) -> DocumentRegistryEntry:
        for document in self.documents.values():
            if document.tenant_id == tenant_id and document.id == document_id:
                return document
        raise DocumentNotFound("Document not found")

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
        document = await self.get(tenant_id, document_id)
        document.attach_upload(
            object_key=object_key,
            checksum_sha256=checksum_sha256,
            detected_mime=detected_mime,
            expected_version=expected_version,
        )
        document.transition(DocumentState.QUARANTINED, expected_version=document.version)
        return document

    async def cancel(
        self, *, tenant_id: UUID, document_id: UUID, expected_version: int
    ) -> DocumentRegistryEntry:
        document = await self.get(tenant_id, document_id)
        document.transition(DocumentState.CANCELLED, expected_version=expected_version)
        return document


class _Store:
    def __init__(self) -> None:
        self.verify_error: ObjectVerificationError | None = None
        self.grant_calls = 0
        self.verify_calls = 0

    async def create_upload_grant(self, document: DocumentRegistryEntry) -> UploadGrant:
        self.grant_calls += 1
        return UploadGrant(
            url="https://object-store.invalid/signed-upload",
            object_key=f"quarantine/{document.tenant_id}/{document.id}/source",
            expires_in_seconds=300,
            required_headers={"Content-Type": document.declared_mime},
        )

    async def verify_upload(
        self, document: DocumentRegistryEntry, object_key: str
    ) -> VerifiedUpload:
        self.verify_calls += 1
        if self.verify_error is not None:
            raise self.verify_error
        return VerifiedUpload(
            object_key=object_key,
            size_bytes=document.declared_size_bytes,
            checksum_sha256="a" * 64,
            detected_mime=document.declared_mime,
        )


class _PurposeAuthorizer:
    def __init__(self) -> None:
        self.denial: ConsentAuthorizationDenied | None = None
        self.calls = 0

    async def authorize(self, **_scope: object) -> None:
        self.calls += 1
        if self.denial is not None:
            raise self.denial


@pytest.fixture
def repository() -> _Repository:
    value = _Repository()
    app.dependency_overrides[get_document_repository] = lambda: value
    yield value
    app.dependency_overrides.pop(get_document_repository, None)


@pytest.fixture(autouse=True)
def purpose_authorizer() -> _PurposeAuthorizer:
    value = _PurposeAuthorizer()
    app.dependency_overrides[get_document_purpose_authorizer] = lambda: value
    yield value
    app.dependency_overrides.pop(get_document_purpose_authorizer, None)


@pytest.fixture
def store() -> _Store:
    value = _Store()
    app.dependency_overrides[get_document_store] = lambda: value
    yield value
    app.dependency_overrides.pop(get_document_store, None)


def _headers(tenant_id: UUID, facility_id: UUID, *, role: str = "nurse") -> dict[str, str]:
    actor_id = uuid4()
    token = create_dev_token(
        str(actor_id),
        "document-reviewer@example.test",
        role,
        str(tenant_id),
        [str(facility_id)],
    )
    return {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": "upload-attempt-1",
    }


def _body(facility_id: UUID) -> dict[str, str | int]:
    return {
        "facility_id": str(facility_id),
        "patient_id": str(uuid4()),
        "encounter_id": str(uuid4()),
        "purpose": "treatment",
        "consent_reference": "consent/test-version-1",
        "original_filename": "prescription.jpg",
        "declared_document_class": "prescription",
        "declared_mime": "image/jpeg",
        "declared_size_bytes": 1024,
    }


def test_authorized_registration_returns_minimal_initiated_resource(
    repository: _Repository,
) -> None:
    tenant_id = uuid4()
    facility_id = uuid4()
    audit_emitter._events.clear()

    response = client.post(
        "/api/v1/documents",
        json=_body(facility_id),
        headers=_headers(tenant_id, facility_id),
    )

    assert response.status_code == 201
    assert response.json()["tenant_id"] == str(tenant_id)
    assert response.json()["facility_id"] == str(facility_id)
    assert response.json()["state"] == "initiated"
    assert response.json()["declared_document_class"] == "prescription"
    assert "original_filename" not in response.json()
    assert "object_key" not in response.json()
    assert repository.create_calls == 1
    assert "prescription.jpg" not in str(audit_emitter._events[-1])


def test_registration_requires_an_explicit_supported_document_class(
    repository: _Repository,
) -> None:
    tenant_id = uuid4()
    facility_id = uuid4()
    body = _body(facility_id)
    body.pop("declared_document_class")

    response = client.post(
        "/api/v1/documents",
        json=body,
        headers=_headers(tenant_id, facility_id),
    )

    assert response.status_code == 422
    assert repository.create_calls == 0


def test_identical_idempotent_retry_returns_existing_resource(repository: _Repository) -> None:
    tenant_id = uuid4()
    facility_id = uuid4()
    headers = _headers(tenant_id, facility_id)
    body = _body(facility_id)

    first = client.post("/api/v1/documents", json=body, headers=headers)
    second = client.post("/api/v1/documents", json=body, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


def test_cross_facility_registration_is_denied_before_repository_access(
    repository: _Repository,
) -> None:
    tenant_id = uuid4()
    authorized_facility = uuid4()

    response = client.post(
        "/api/v1/documents",
        json=_body(uuid4()),
        headers=_headers(tenant_id, authorized_facility),
    )

    assert response.status_code == 403
    assert repository.create_calls == 0


def test_registration_fails_closed_when_consent_is_not_active(
    repository: _Repository,
    purpose_authorizer: _PurposeAuthorizer,
) -> None:
    tenant_id = uuid4()
    facility_id = uuid4()
    purpose_authorizer.denial = ConsentAuthorizationDenied()

    response = client.post(
        "/api/v1/documents",
        json=_body(facility_id),
        headers=_headers(tenant_id, facility_id),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Active consent does not authorize this upload"}
    assert repository.create_calls == 0


def test_unapproved_role_cannot_register_a_document(repository: _Repository) -> None:
    tenant_id = uuid4()
    facility_id = uuid4()

    response = client.post(
        "/api/v1/documents",
        json=_body(facility_id),
        headers=_headers(tenant_id, facility_id, role="auditor"),
    )

    assert response.status_code == 403
    assert repository.create_calls == 0


def test_conflicting_idempotency_key_returns_conflict(repository: _Repository) -> None:
    tenant_id = uuid4()
    facility_id = uuid4()
    headers = _headers(tenant_id, facility_id)
    body = _body(facility_id)
    client.post("/api/v1/documents", json=body, headers=headers)
    body["original_filename"] = "different.jpg"

    response = client.post("/api/v1/documents", json=body, headers=headers)

    assert response.status_code == 409


def test_registration_requires_an_idempotency_key(repository: _Repository) -> None:
    tenant_id = uuid4()
    facility_id = uuid4()
    headers = _headers(tenant_id, facility_id)
    headers.pop("Idempotency-Key")

    response = client.post(
        "/api/v1/documents",
        json=_body(facility_id),
        headers=headers,
    )

    assert response.status_code == 422
    assert repository.create_calls == 0


def test_document_workflow_fails_closed_when_not_enabled() -> None:
    tenant_id = uuid4()
    facility_id = uuid4()

    response = client.post(
        "/api/v1/documents",
        json=_body(facility_id),
        headers=_headers(tenant_id, facility_id),
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Document workflow is not enabled"}


def test_authorized_user_gets_a_short_lived_upload_grant(
    repository: _Repository, store: _Store
) -> None:
    tenant_id = uuid4()
    facility_id = uuid4()
    headers = _headers(tenant_id, facility_id)
    created = client.post("/api/v1/documents", json=_body(facility_id), headers=headers)

    response = client.post(
        f"/api/v1/documents/{created.json()['id']}/upload-session",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["url"].startswith("https://")
    assert response.json()["expires_in_seconds"] == 300
    assert "object_key" not in response.json()
    assert store.grant_calls == 1


def test_authorized_user_can_read_document_status(repository: _Repository) -> None:
    tenant_id = uuid4()
    facility_id = uuid4()
    headers = _headers(tenant_id, facility_id)
    created = client.post("/api/v1/documents", json=_body(facility_id), headers=headers)

    response = client.get(
        f"/api/v1/documents/{created.json()['id']}",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["state"] == "initiated"
    assert "upload_expires_at" in response.json()


def test_authorized_user_can_cancel_an_initiated_upload(repository: _Repository) -> None:
    tenant_id = uuid4()
    facility_id = uuid4()
    headers = _headers(tenant_id, facility_id)
    created = client.post("/api/v1/documents", json=_body(facility_id), headers=headers)

    response = client.post(
        f"/api/v1/documents/{created.json()['id']}/cancel",
        json={"expected_version": 1},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["state"] == "cancelled"
    assert response.json()["version"] == 2


def test_cancel_rejects_a_stale_version(repository: _Repository) -> None:
    tenant_id = uuid4()
    facility_id = uuid4()
    headers = _headers(tenant_id, facility_id)
    created = client.post("/api/v1/documents", json=_body(facility_id), headers=headers)

    response = client.post(
        f"/api/v1/documents/{created.json()['id']}/cancel",
        json={"expected_version": 2},
        headers=headers,
    )

    assert response.status_code == 409


def test_finalize_verifies_object_then_moves_document_to_quarantine(
    repository: _Repository, store: _Store
) -> None:
    tenant_id = uuid4()
    facility_id = uuid4()
    headers = _headers(tenant_id, facility_id)
    created = client.post("/api/v1/documents", json=_body(facility_id), headers=headers)

    response = client.post(
        f"/api/v1/documents/{created.json()['id']}/finalize",
        json={"expected_version": 1},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["state"] == "quarantined"
    assert response.json()["version"] == 3
    assert store.verify_calls == 1


def test_finalize_rejects_unverified_object_without_changing_registry(
    repository: _Repository, store: _Store
) -> None:
    tenant_id = uuid4()
    facility_id = uuid4()
    headers = _headers(tenant_id, facility_id)
    created = client.post("/api/v1/documents", json=_body(facility_id), headers=headers)
    store.verify_error = ObjectVerificationError("size mismatch")

    response = client.post(
        f"/api/v1/documents/{created.json()['id']}/finalize",
        json={"expected_version": 1},
        headers=headers,
    )

    assert response.status_code == 422
    document = next(iter(repository.documents.values()))
    assert document.state is DocumentState.INITIATED
