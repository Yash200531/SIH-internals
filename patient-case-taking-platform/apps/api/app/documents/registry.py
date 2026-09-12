"""Document registry domain model.

This module deliberately contains no object-store or database adapter. It is the
state and concurrency contract those Phase 7 adapters must enforce.
"""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from app.models.base import BaseRecord


class DocumentState(StrEnum):
    INITIATED = "initiated"
    UPLOADED = "uploaded"
    QUARANTINED = "quarantined"
    SCANNING = "scanning"
    SCAN_REJECTED = "scan_rejected"
    SCAN_PASSED = "scan_passed"
    PROCESSING = "processing"
    PROCESSING_FAILED = "processing_failed"
    REVIEW_REQUIRED = "review_required"
    REVIEWED = "reviewed"
    CANCELLED = "cancelled"
    RETENTION_HOLD = "retention_hold"
    DELETION_PENDING = "deletion_pending"


ALLOWED_TRANSITIONS: dict[DocumentState, frozenset[DocumentState]] = {
    DocumentState.INITIATED: frozenset({DocumentState.UPLOADED, DocumentState.CANCELLED}),
    DocumentState.UPLOADED: frozenset({DocumentState.QUARANTINED, DocumentState.CANCELLED}),
    DocumentState.QUARANTINED: frozenset({DocumentState.SCANNING, DocumentState.CANCELLED}),
    DocumentState.SCANNING: frozenset(
        {
            DocumentState.SCAN_REJECTED,
            DocumentState.SCAN_PASSED,
            DocumentState.PROCESSING_FAILED,
        }
    ),
    DocumentState.SCAN_PASSED: frozenset(
        {DocumentState.PROCESSING, DocumentState.CANCELLED}
    ),
    DocumentState.PROCESSING: frozenset(
        {DocumentState.REVIEW_REQUIRED, DocumentState.PROCESSING_FAILED}
    ),
    DocumentState.PROCESSING_FAILED: frozenset(
        {
            DocumentState.SCANNING,
            DocumentState.PROCESSING,
            DocumentState.REVIEW_REQUIRED,
            DocumentState.CANCELLED,
        }
    ),
    DocumentState.REVIEW_REQUIRED: frozenset({DocumentState.REVIEWED}),
    DocumentState.REVIEWED: frozenset(
        {DocumentState.RETENTION_HOLD, DocumentState.DELETION_PENDING}
    ),
    DocumentState.SCAN_REJECTED: frozenset(
        {DocumentState.RETENTION_HOLD, DocumentState.DELETION_PENDING}
    ),
    DocumentState.CANCELLED: frozenset({DocumentState.DELETION_PENDING}),
    DocumentState.RETENTION_HOLD: frozenset(),
    DocumentState.DELETION_PENDING: frozenset(),
}


class InvalidDocumentTransition(ValueError):
    """Raised when a document lifecycle transition is not allowed."""


class ConcurrentDocumentUpdate(ValueError):
    """Raised when an update uses a stale registry version."""


class DocumentRegistryEntry(BaseRecord):
    facility_id: UUID
    patient_id: UUID
    encounter_id: UUID
    uploader_actor_id: UUID
    purpose: str = Field(min_length=1, max_length=64)
    consent_reference: str = Field(min_length=1, max_length=256)
    original_filename: str = Field(min_length=1, max_length=255)
    declared_document_class: str = Field(default="unknown", min_length=1, max_length=64)
    suggested_document_class: str | None = Field(default=None, max_length=64)
    reviewed_document_class: str | None = Field(default=None, max_length=64)
    declared_mime: str = Field(min_length=1, max_length=127)
    declared_size_bytes: int = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=128)
    upload_expires_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC) + timedelta(minutes=15)
    )
    state: DocumentState = DocumentState.INITIATED
    object_key: str | None = None
    source_checksum_sha256: str | None = None
    detected_mime: str | None = None
    active_processing_run_id: UUID | None = None
    active_normalization_run_id: UUID | None = None
    active_ocr_run_id: UUID | None = None
    active_extraction_run_id: UUID | None = None
    processing_object_key: str | None = None

    def record_processing_progress(self, *, expected_version: int) -> None:
        self._assert_version(expected_version)
        if self.state is not DocumentState.PROCESSING:
            raise InvalidDocumentTransition("Processing progress requires processing state")
        self.version += 1
        self.updated_at = datetime.now(UTC)

    def _assert_version(self, expected_version: int) -> None:
        if expected_version != self.version:
            raise ConcurrentDocumentUpdate(
                f"Expected document version {expected_version}; current version is {self.version}"
            )

    def _assert_transition(self, next_state: DocumentState, expected_version: int) -> None:
        self._assert_version(expected_version)
        if next_state not in ALLOWED_TRANSITIONS[self.state]:
            raise InvalidDocumentTransition(f"Cannot transition {self.state} to {next_state}")

    def transition(self, next_state: DocumentState, *, expected_version: int) -> None:
        self._assert_transition(next_state, expected_version)
        self.state = next_state
        self.version += 1
        self.updated_at = datetime.now(UTC)

    def attach_upload(
        self,
        *,
        object_key: str,
        checksum_sha256: str,
        detected_mime: str,
        expected_version: int,
    ) -> None:
        if self.upload_expires_at <= datetime.now(UTC):
            raise InvalidDocumentTransition("Upload session has expired")
        self._assert_transition(DocumentState.UPLOADED, expected_version)
        expected_prefix = f"quarantine/{self.tenant_id}/{self.id}/"
        if not object_key.startswith(expected_prefix):
            raise ValueError("Object key must be scoped to this document's quarantine prefix")
        if len(checksum_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in checksum_sha256.lower()
        ):
            raise ValueError("Checksum must be a hexadecimal SHA-256 digest")
        if not detected_mime:
            raise ValueError("Detected MIME type is required")

        self.object_key = object_key
        self.source_checksum_sha256 = checksum_sha256.lower()
        self.detected_mime = detected_mime
        self.transition(DocumentState.UPLOADED, expected_version=expected_version)
