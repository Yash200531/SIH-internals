"""Private quarantine object-store contract tests."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.documents.storage import ObjectVerificationError, PageArtifact, S3DocumentStore


class _Body:
    def __init__(self, data: bytes):
        self.data = data
        self.closed = False

    def iter_chunks(self, chunk_size: int):
        for offset in range(0, len(self.data), chunk_size):
            yield self.data[offset : offset + chunk_size]

    def close(self) -> None:
        self.closed = True


class _Client:
    def __init__(self, data: bytes, content_type: str):
        self.data = data
        self.content_type = content_type
        self.presign_params: dict[str, Any] | None = None
        self.body = _Body(data)
        self.copy_params: dict[str, Any] | None = None
        self.put_params: list[dict[str, Any]] = []

    def generate_presigned_url(self, operation: str, **kwargs: Any) -> str:
        self.presign_params = {"operation": operation, **kwargs}
        return "https://object-store.invalid/signed-upload"

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {"ContentLength": len(self.data), "ContentType": self.content_type}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {"Body": self.body}

    def copy_object(self, **kwargs: Any) -> None:
        self.copy_params = kwargs

    def put_object(self, **kwargs: Any) -> None:
        self.put_params.append(kwargs)


def _document(*, size: int, mime: str = "image/jpeg") -> DocumentRegistryEntry:
    from uuid import uuid4

    return DocumentRegistryEntry(
        tenant_id=uuid4(),
        facility_id=uuid4(),
        patient_id=uuid4(),
        encounter_id=uuid4(),
        uploader_actor_id=uuid4(),
        purpose="treatment",
        consent_reference="consent/test-version-1",
        original_filename="prescription.jpg",
        declared_mime=mime,
        declared_size_bytes=size,
        idempotency_key="upload-attempt-1",
    )


@pytest.mark.asyncio
async def test_upload_grant_is_scoped_to_one_quarantine_object() -> None:
    data = b"\xff\xd8\xff" + b"safe-image"
    document = _document(size=len(data))
    client = _Client(data, "image/jpeg")
    presign_client = _Client(data, "image/jpeg")
    store = S3DocumentStore(
        client=client,
        presign_client=presign_client,
        bucket="clinical-private",
        grant_ttl_seconds=300,
        server_side_encryption="AES256",
    )

    grant = await store.create_upload_grant(document)

    expected_key = f"quarantine/{document.tenant_id}/{document.id}/source"
    assert grant.object_key == expected_key
    assert grant.expires_in_seconds == 300
    assert grant.required_headers["Content-Type"] == "image/jpeg"
    assert client.presign_params is None
    assert presign_client.presign_params is not None
    assert presign_client.presign_params["Params"]["Key"] == expected_key
    assert presign_client.presign_params["Params"]["ContentLength"] == len(data)
    assert grant.required_headers["x-amz-server-side-encryption"] == "AES256"


@pytest.mark.asyncio
async def test_upload_grant_requires_encryption_outside_development(monkeypatch) -> None:
    data = b"\xff\xd8\xff" + b"safe-image"
    document = _document(size=len(data))
    store = S3DocumentStore(
        client=_Client(data, "image/jpeg"),
        bucket="clinical-private",
        server_side_encryption="",
    )
    monkeypatch.setattr("app.documents.storage.settings.APP_ENV", "production")

    with pytest.raises(ObjectVerificationError, match="encryption"):
        await store.create_upload_grant(document)


@pytest.mark.asyncio
async def test_upload_grant_is_denied_after_session_expiry() -> None:
    data = b"\xff\xd8\xff" + b"safe-image"
    document = _document(size=len(data)).model_copy(
        update={"upload_expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )
    store = S3DocumentStore(
        client=_Client(data, "image/jpeg"),
        bucket="clinical-private",
    )

    with pytest.raises(ObjectVerificationError, match="expired"):
        await store.create_upload_grant(document)


@pytest.mark.asyncio
async def test_verify_upload_hashes_bytes_and_detects_mime_from_magic_bytes() -> None:
    data = b"\xff\xd8\xff" + b"safe-image"
    document = _document(size=len(data))
    client = _Client(data, "image/jpeg")
    store = S3DocumentStore(client=client, bucket="clinical-private")
    object_key = f"quarantine/{document.tenant_id}/{document.id}/source"

    verified = await store.verify_upload(document, object_key)

    assert verified.size_bytes == len(data)
    assert verified.detected_mime == "image/jpeg"
    assert verified.checksum_sha256 == hashlib.sha256(data).hexdigest()
    assert client.body.closed is True


@pytest.mark.asyncio
async def test_verify_upload_rejects_declared_mime_spoofing() -> None:
    data = b"%PDF-1.7\nsynthetic"
    document = _document(size=len(data), mime="image/jpeg")
    store = S3DocumentStore(client=_Client(data, "image/jpeg"), bucket="clinical-private")
    object_key = f"quarantine/{document.tenant_id}/{document.id}/source"

    with pytest.raises(ObjectVerificationError, match="type"):
        await store.verify_upload(document, object_key)


@pytest.mark.asyncio
async def test_verify_upload_rejects_size_mismatch_before_reading() -> None:
    data = b"\xff\xd8\xff" + b"safe-image"
    document = _document(size=len(data) + 1)
    client = _Client(data, "image/jpeg")
    store = S3DocumentStore(client=client, bucket="clinical-private")
    object_key = f"quarantine/{document.tenant_id}/{document.id}/source"

    with pytest.raises(ObjectVerificationError, match="size"):
        await store.verify_upload(document, object_key)

    assert client.body.closed is False


@pytest.mark.asyncio
async def test_scan_read_reverifies_immutable_source_checksum() -> None:
    data = b"\xff\xd8\xff" + b"safe-image"
    document = _document(size=len(data))
    document.attach_upload(
        object_key=f"quarantine/{document.tenant_id}/{document.id}/source",
        checksum_sha256=hashlib.sha256(data).hexdigest(),
        detected_mime="image/jpeg",
        expected_version=1,
    )
    document.transition(DocumentState.QUARANTINED, expected_version=2)
    document.transition(DocumentState.SCANNING, expected_version=3)
    client = _Client(data, "image/jpeg")
    store = S3DocumentStore(client=client, bucket="clinical-private")

    payload = await store.read_for_scan(document)

    assert payload == data
    assert client.body.closed is True


@pytest.mark.asyncio
async def test_only_scanning_document_can_be_promoted_to_processing_prefix() -> None:
    data = b"\xff\xd8\xff" + b"safe-image"
    document = _document(size=len(data))
    document.attach_upload(
        object_key=f"quarantine/{document.tenant_id}/{document.id}/source",
        checksum_sha256=hashlib.sha256(data).hexdigest(),
        detected_mime="image/jpeg",
        expected_version=1,
    )
    document.transition(DocumentState.QUARANTINED, expected_version=2)
    document.transition(DocumentState.SCANNING, expected_version=3)
    client = _Client(data, "image/jpeg")
    store = S3DocumentStore(
        client=client,
        bucket="clinical-private",
        server_side_encryption="AES256",
    )

    destination = await store.promote_after_clean_scan(document, "run-1")

    assert destination.startswith(
        f"clinical-processing/{document.tenant_id}/{document.id}/run-1/"
    )
    assert client.copy_params is not None
    assert client.copy_params["CopySource"]["Key"] == document.object_key
    assert client.copy_params["ServerSideEncryption"] == "AES256"


@pytest.mark.asyncio
async def test_normalized_pages_are_stored_under_versioned_derived_prefix() -> None:
    from app.documents.normalization import NormalizedPage

    data = b"\xff\xd8\xff" + b"safe-image"
    document = _document(size=len(data)).model_copy(
        update={
            "state": DocumentState.PROCESSING,
            "version": 6,
            "processing_object_key": "clinical-processing/source",
            "source_checksum_sha256": hashlib.sha256(data).hexdigest(),
        }
    )
    page_data = b"\x89PNG\r\n\x1a\nsynthetic"
    page = NormalizedPage(
        page_number=1,
        width=20,
        height=30,
        mime="image/png",
        data=page_data,
        checksum_sha256=hashlib.sha256(page_data).hexdigest(),
    )
    client = _Client(data, "image/jpeg")
    store = S3DocumentStore(
        client=client,
        bucket="clinical-private",
        server_side_encryption="AES256",
    )

    stored = await store.store_normalized_pages(document, "normalize-run-1", [page])

    assert stored[0].object_key == (
        f"derived/{document.tenant_id}/{document.id}/normalize-run-1/pages/0001.png"
    )
    assert client.put_params[0]["Body"] == page_data
    assert client.put_params[0]["Metadata"]["source-checksum"] == (
        document.source_checksum_sha256
    )


@pytest.mark.asyncio
async def test_ocr_read_reverifies_scoped_normalized_page_checksum() -> None:
    from uuid import uuid4

    page_data = b"\x89PNG\r\n\x1a\nsynthetic"
    document = _document(size=12).model_copy(
        update={"state": DocumentState.PROCESSING, "version": 7}
    )
    run_id = uuid4()
    page = PageArtifact(
        id=uuid4(),
        page_number=1,
        object_key=f"derived/{document.tenant_id}/{document.id}/{run_id}/pages/0001.png",
        checksum_sha256=hashlib.sha256(page_data).hexdigest(),
        mime="image/png",
        width=20,
        height=30,
        preprocessing_version="normalize.v1",
    )
    client = _Client(page_data, "image/png")
    store = S3DocumentStore(client=client, bucket="clinical-private")

    payload = await store.read_normalized_page(document, page, max_bytes=1024)

    assert payload == page_data
    assert client.body.closed is True


@pytest.mark.asyncio
async def test_ocr_read_rejects_page_outside_document_scope() -> None:
    from uuid import uuid4

    page_data = b"\x89PNG\r\n\x1a\nsynthetic"
    document = _document(size=12).model_copy(
        update={"state": DocumentState.PROCESSING, "version": 7}
    )
    page = PageArtifact(
        id=uuid4(),
        page_number=1,
        object_key=f"derived/{uuid4()}/{document.id}/run/pages/0001.png",
        checksum_sha256=hashlib.sha256(page_data).hexdigest(),
        mime="image/png",
        width=20,
        height=30,
        preprocessing_version="normalize.v1",
    )
    store = S3DocumentStore(
        client=_Client(page_data, "image/png"),
        bucket="clinical-private",
    )

    with pytest.raises(ObjectVerificationError, match="scope"):
        await store.read_normalized_page(document, page, max_bytes=1024)


@pytest.mark.asyncio
async def test_review_preview_is_short_lived_and_scoped_to_exact_page(monkeypatch) -> None:
    from uuid import uuid4

    document = _document(size=12).model_copy(
        update={"state": DocumentState.REVIEW_REQUIRED, "version": 9}
    )
    page = PageArtifact(
        id=uuid4(),
        page_number=1,
        object_key=f"derived/{document.tenant_id}/{document.id}/run/pages/0001.png",
        checksum_sha256="a" * 64,
        mime="image/png",
        width=20,
        height=30,
        preprocessing_version="normalize.v1",
    )
    client = _Client(b"page", "image/png")
    store = S3DocumentStore(
        client=client,
        presign_client=client,
        bucket="clinical-private",
    )
    monkeypatch.setattr(
        "app.documents.storage.settings.DOCUMENT_PREVIEW_GRANT_TTL_SECONDS", 180
    )

    grant = await store.create_page_preview_grant(document, page)

    assert grant.expires_in_seconds == 180
    assert client.presign_params is not None
    assert client.presign_params["operation"] == "get_object"
    assert client.presign_params["Params"] == {
        "Bucket": "clinical-private",
        "Key": page.object_key,
    }


@pytest.mark.asyncio
async def test_review_preview_rejects_cross_document_page() -> None:
    from uuid import uuid4

    document = _document(size=12).model_copy(
        update={"state": DocumentState.REVIEW_REQUIRED, "version": 9}
    )
    page = PageArtifact(
        id=uuid4(),
        page_number=1,
        object_key=f"derived/{document.tenant_id}/{uuid4()}/run/pages/0001.png",
        checksum_sha256="a" * 64,
        mime="image/png",
        width=20,
        height=30,
        preprocessing_version="normalize.v1",
    )
    store = S3DocumentStore(client=_Client(b"page", "image/png"))

    with pytest.raises(ObjectVerificationError, match="scope"):
        await store.create_page_preview_grant(document, page)
