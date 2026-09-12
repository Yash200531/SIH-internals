"""Phase 7 document-registry domain contract tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.documents.registry import (
    ConcurrentDocumentUpdate,
    DocumentRegistryEntry,
    DocumentState,
    InvalidDocumentTransition,
)


def _document() -> DocumentRegistryEntry:
    return DocumentRegistryEntry(
        tenant_id=uuid4(),
        facility_id=uuid4(),
        patient_id=uuid4(),
        encounter_id=uuid4(),
        uploader_actor_id=uuid4(),
        purpose="treatment",
        consent_reference="consent/test-version-1",
        original_filename="prescription.jpg",
        declared_mime="image/jpeg",
        declared_size_bytes=1024,
        idempotency_key="upload-attempt-1",
    )


def test_document_starts_in_initiated_state_without_an_object_reference() -> None:
    document = _document()

    assert document.state is DocumentState.INITIATED
    assert document.version == 1
    assert document.object_key is None
    assert document.source_checksum_sha256 is None


def test_document_follows_the_quarantine_processing_state_machine() -> None:
    document = _document()
    document.attach_upload(
        object_key=f"quarantine/{document.tenant_id}/{document.id}/source",
        checksum_sha256="a" * 64,
        detected_mime="image/jpeg",
        expected_version=1,
    )

    expected_states = (
        DocumentState.QUARANTINED,
        DocumentState.SCANNING,
        DocumentState.SCAN_PASSED,
        DocumentState.PROCESSING,
        DocumentState.REVIEW_REQUIRED,
        DocumentState.REVIEWED,
    )

    for expected_state in expected_states:
        previous_version = document.version
        document.transition(expected_state, expected_version=previous_version)
        assert document.state is expected_state
        assert document.version == previous_version + 1


def test_document_rejects_skipping_quarantine_and_scan() -> None:
    document = _document()

    with pytest.raises(InvalidDocumentTransition):
        document.transition(DocumentState.PROCESSING, expected_version=1)

    assert document.state is DocumentState.INITIATED
    assert document.version == 1


def test_document_rejects_a_stale_optimistic_concurrency_version() -> None:
    document = _document()
    document.attach_upload(
        object_key=f"quarantine/{document.tenant_id}/{document.id}/source",
        checksum_sha256="a" * 64,
        detected_mime="image/jpeg",
        expected_version=1,
    )

    with pytest.raises(ConcurrentDocumentUpdate):
        document.transition(DocumentState.QUARANTINED, expected_version=1)

    assert document.state is DocumentState.UPLOADED
    assert document.version == 2


def test_scan_rejected_document_cannot_enter_processing() -> None:
    document = _document()
    document.attach_upload(
        object_key=f"quarantine/{document.tenant_id}/{document.id}/source",
        checksum_sha256="a" * 64,
        detected_mime="image/jpeg",
        expected_version=1,
    )
    document.transition(DocumentState.QUARANTINED, expected_version=2)
    document.transition(DocumentState.SCANNING, expected_version=3)
    document.transition(DocumentState.SCAN_REJECTED, expected_version=4)

    with pytest.raises(InvalidDocumentTransition):
        document.transition(DocumentState.PROCESSING, expected_version=5)


def test_upload_attachment_rejects_non_quarantine_object_keys() -> None:
    document = _document()

    with pytest.raises(ValueError, match="quarantine"):
        document.attach_upload(
            object_key=f"clinical/{document.tenant_id}/{document.id}/source",
            checksum_sha256="a" * 64,
            detected_mime="image/jpeg",
            expected_version=1,
        )

    assert document.state is DocumentState.INITIATED
    assert document.object_key is None


def test_rejected_second_upload_does_not_replace_the_immutable_source() -> None:
    document = _document()
    original_key = f"quarantine/{document.tenant_id}/{document.id}/source"
    document.attach_upload(
        object_key=original_key,
        checksum_sha256="a" * 64,
        detected_mime="image/jpeg",
        expected_version=1,
    )

    with pytest.raises(InvalidDocumentTransition):
        document.attach_upload(
            object_key=f"quarantine/{document.tenant_id}/{document.id}/replacement",
            checksum_sha256="b" * 64,
            detected_mime="image/png",
            expected_version=2,
        )

    assert document.object_key == original_key
    assert document.source_checksum_sha256 == "a" * 64
    assert document.detected_mime == "image/jpeg"


def test_expired_upload_session_cannot_attach_an_object() -> None:
    document = _document().model_copy(
        update={"upload_expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )

    with pytest.raises(InvalidDocumentTransition, match="expired"):
        document.attach_upload(
            object_key=f"quarantine/{document.tenant_id}/{document.id}/source",
            checksum_sha256="a" * 64,
            detected_mime="image/jpeg",
            expected_version=1,
        )

    assert document.state is DocumentState.INITIATED


def test_processing_artifact_progress_advances_version_without_changing_state() -> None:
    document = _document().model_copy(update={"state": DocumentState.PROCESSING, "version": 6})

    document.record_processing_progress(expected_version=6)

    assert document.state is DocumentState.PROCESSING
    assert document.version == 7
