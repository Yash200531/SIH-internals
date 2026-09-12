"""OCR orchestration durability and fail-closed behavior tests."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.documents.ocr_artifact import DocumentOcrArtifact
from app.documents.ocr_artifact_store import OcrArtifactStoreUnavailable
from app.documents.ocr_repository import DocumentOcrRun, OcrStartResult
from app.documents.ocr_service import DocumentOcrService
from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.documents.storage import ObjectVerificationError, PageArtifact
from app.ocr.base import OCRRegion, OCRResult


def _started() -> OcrStartResult:
    document = DocumentRegistryEntry(
        tenant_id=uuid4(),
        facility_id=uuid4(),
        patient_id=uuid4(),
        encounter_id=uuid4(),
        uploader_actor_id=uuid4(),
        purpose="treatment",
        consent_reference=str(uuid4()),
        original_filename="synthetic.png",
        declared_mime="image/png",
        declared_size_bytes=16,
        idempotency_key="ocr-service-test",
        state=DocumentState.PROCESSING,
        version=8,
        source_checksum_sha256="a" * 64,
        active_normalization_run_id=uuid4(),
    )
    now = datetime.now(UTC)
    run = DocumentOcrRun(
        id=uuid4(),
        tenant_id=document.tenant_id,
        document_id=document.id,
        normalization_run_id=document.active_normalization_run_id,
        attempt=1,
        provider="mock",
        model_version="mock-ocr-v1",
        language_pack_version="synthetic-en-v1",
        schema_version="DocumentOcrArtifact.v1",
        status="running",
        started_at=now,
        lease_expires_at=now + timedelta(minutes=2),
    )
    pages = [
        PageArtifact(
            id=uuid4(),
            page_number=1,
            object_key=f"derived/{document.tenant_id}/{document.id}/run/pages/0001.png",
            checksum_sha256="b" * 64,
            mime="image/png",
            width=100,
            height=40,
            preprocessing_version="normalize.v1",
        )
    ]
    return OcrStartResult(document, run, pages)


class _Repository:
    def __init__(self, started: OcrStartResult, complete_error: Exception | None = None) -> None:
        self.started = started
        self.complete_error = complete_error
        self.completed: dict[str, object] | None = None
        self.failed: dict[str, object] | None = None

    async def start(self, **_values: object) -> OcrStartResult:
        return self.started

    async def complete(self, **values: object) -> DocumentRegistryEntry:
        if self.complete_error is not None:
            raise self.complete_error
        self.completed = values
        return self.started.document

    async def fail(self, **values: object) -> DocumentRegistryEntry:
        self.failed = values
        return self.started.document


class _Store:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def read_normalized_page(
        self,
        _document: DocumentRegistryEntry,
        _page: PageArtifact,
        *,
        max_bytes: int,
    ) -> bytes:
        assert max_bytes > 0
        if self.error is not None:
            raise self.error
        return b"normalized-page"


class _Provider:
    provider_name = "mock"
    model_version = "mock-ocr-v1"
    language_pack_version = "synthetic-en-v1"

    def __init__(self, error: Exception | None = None, wait: bool = False) -> None:
        self.error = error
        self.wait = wait

    async def recognize(self, _payload: bytes, mime_type: str = "image/png") -> OCRResult:
        assert mime_type == "image/png"
        if self.wait:
            await asyncio.sleep(1)
        if self.error is not None:
            raise self.error
        return OCRResult(
            text="Synthetic prescription",
            regions=[
                OCRRegion(
                    text="Synthetic prescription",
                    confidence=None,
                    bbox=(1, 2, 90, 20),
                )
            ],
            confidence=None,
            provider=self.provider_name,
            model_version=self.model_version,
            language_pack_version=self.language_pack_version,
            duration_ms=1,
        )


class _ArtifactStore:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.saved: list[DocumentOcrArtifact] = []

    async def save(self, artifact: DocumentOcrArtifact) -> bool:
        if self.error is not None:
            raise self.error
        self.saved.append(artifact)
        return True


@pytest.mark.asyncio
async def test_ocr_artifacts_are_saved_before_postgres_completion() -> None:
    started = _started()
    repository = _Repository(started)
    artifacts = _ArtifactStore()
    service = DocumentOcrService(repository, _Store(), artifacts, _Provider())

    await service.process(
        tenant_id=started.document.tenant_id,
        document_id=started.document.id,
        expected_version=7,
    )

    assert len(artifacts.saved) == 1
    assert repository.completed is not None
    assert repository.completed["artifacts"] == artifacts.saved
    assert repository.failed is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("store_error", "provider_error", "error_class"),
    [
        (ObjectVerificationError("raw object detail"), None, "page_verification_error"),
        (None, ValueError("raw provider detail"), "provider_error"),
    ],
)
async def test_page_and_provider_failures_persist_safe_retry_classes(
    store_error: Exception | None,
    provider_error: Exception | None,
    error_class: str,
) -> None:
    started = _started()
    repository = _Repository(started)
    service = DocumentOcrService(
        repository,
        _Store(store_error),
        _ArtifactStore(),
        _Provider(provider_error),
    )

    await service.process(
        tenant_id=started.document.tenant_id,
        document_id=started.document.id,
        expected_version=7,
    )

    assert repository.failed is not None
    assert repository.failed["error_class"] == error_class
    assert "raw" not in str(repository.failed)


@pytest.mark.asyncio
async def test_artifact_store_denial_is_retryable_without_postgres_completion() -> None:
    started = _started()
    repository = _Repository(started)
    service = DocumentOcrService(
        repository,
        _Store(),
        _ArtifactStore(OcrArtifactStoreUnavailable("raw mongo detail")),
        _Provider(),
    )

    await service.process(
        tenant_id=started.document.tenant_id,
        document_id=started.document.id,
        expected_version=7,
    )

    assert repository.completed is None
    assert repository.failed is not None
    assert repository.failed["error_class"] == "artifact_store_error"


@pytest.mark.asyncio
async def test_provider_timeout_is_retryable() -> None:
    started = _started()
    repository = _Repository(started)
    service = DocumentOcrService(
        repository,
        _Store(),
        _ArtifactStore(),
        _Provider(wait=True),
        timeout_seconds=0.001,
    )

    await service.process(
        tenant_id=started.document.tenant_id,
        document_id=started.document.id,
        expected_version=7,
    )

    assert repository.failed is not None
    assert repository.failed["error_class"] == "provider_timeout"


@pytest.mark.asyncio
async def test_postgres_completion_failure_leaves_run_reclaimable() -> None:
    started = _started()
    repository = _Repository(started, complete_error=RuntimeError("postgres unavailable"))
    service = DocumentOcrService(
        repository,
        _Store(),
        _ArtifactStore(),
        _Provider(),
    )

    with pytest.raises(RuntimeError, match="postgres unavailable"):
        await service.process(
            tenant_id=started.document.tenant_id,
            document_id=started.document.id,
            expected_version=7,
        )

    assert repository.failed is None
