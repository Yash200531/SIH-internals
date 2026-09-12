"""Page-normalization orchestration tests with deterministic fakes."""

import time
from uuid import uuid4

import pytest

from app.documents.normalization import (
    DocumentNormalizationError,
    NormalizedPage,
)
from app.documents.normalization_repository import (
    DocumentNormalizationRun,
    NormalizationStartResult,
)
from app.documents.normalization_service import DocumentNormalizationService
from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.documents.storage import ObjectVerificationError, StoredPage


def _processing_document() -> DocumentRegistryEntry:
    return DocumentRegistryEntry(
        tenant_id=uuid4(),
        facility_id=uuid4(),
        patient_id=uuid4(),
        encounter_id=uuid4(),
        uploader_actor_id=uuid4(),
        purpose="treatment",
        consent_reference=str(uuid4()),
        original_filename="synthetic.jpg",
        declared_mime="image/jpeg",
        declared_size_bytes=4,
        idempotency_key="normalization-service-test",
        state=DocumentState.PROCESSING,
        version=6,
        source_checksum_sha256="a" * 64,
        detected_mime="image/jpeg",
        processing_object_key="clinical-processing/tenant/document/run/source",
    )


class _Repository:
    def __init__(self, document: DocumentRegistryEntry) -> None:
        self.document = document
        self.run = DocumentNormalizationRun(
            id=uuid4(),
            tenant_id=document.tenant_id,
            document_id=document.id,
            attempt=1,
            preprocessing_version="normalize.v1",
            started_at=document.created_at,
        )
        self.completed: dict[str, object] | None = None
        self.failed: dict[str, object] | None = None

    async def start(self, **_scope: object) -> NormalizationStartResult:
        return NormalizationStartResult(self.document, self.run)

    async def complete(self, **values: object) -> DocumentRegistryEntry:
        self.completed = values
        return self.document

    async def fail(self, **values: object) -> DocumentRegistryEntry:
        self.failed = values
        return self.document


class _Store:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.stored = False

    async def read_processing_source(self, _document: DocumentRegistryEntry) -> bytes:
        if self.error is not None:
            raise self.error
        return b"safe"

    async def store_normalized_pages(
        self,
        document: DocumentRegistryEntry,
        normalization_run_id: str,
        pages: list[NormalizedPage],
    ) -> list[StoredPage]:
        self.stored = True
        return [
            StoredPage(
                page_number=page.page_number,
                object_key=(
                    f"derived/{document.tenant_id}/{document.id}/"
                    f"{normalization_run_id}/pages/{page.page_number:04d}.png"
                ),
                checksum_sha256=page.checksum_sha256,
                mime=page.mime,
                width=page.width,
                height=page.height,
                preprocessing_version=page.preprocessing_version,
                operations=page.operations,
            )
            for page in pages
        ]


class _Normalizer:
    def __init__(self, result: list[NormalizedPage] | Exception, delay: float = 0) -> None:
        self.result = result
        self.delay = delay

    def normalize(self, _payload: bytes, _mime: str) -> list[NormalizedPage]:
        if self.delay:
            time.sleep(self.delay)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _page() -> NormalizedPage:
    return NormalizedPage(
        page_number=1,
        width=2,
        height=2,
        mime="image/png",
        data=b"normalized",
        checksum_sha256="b" * 64,
    )


@pytest.mark.asyncio
async def test_normalization_stores_pages_before_completing_run() -> None:
    document = _processing_document()
    repository = _Repository(document)
    store = _Store()
    service = DocumentNormalizationService(repository, store, _Normalizer([_page()]))

    await service.process(
        tenant_id=document.tenant_id,
        document_id=document.id,
        expected_version=5,
    )

    assert store.stored is True
    assert repository.completed is not None
    assert repository.completed["expected_version"] == 6
    assert repository.failed is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "error_class"),
    [
        (DocumentNormalizationError("raw parser detail"), "normalization_rejected"),
        (ObjectVerificationError("raw storage detail"), "source_verification_error"),
    ],
)
async def test_expected_normalization_failures_persist_safe_classes(
    error: Exception,
    error_class: str,
) -> None:
    document = _processing_document()
    repository = _Repository(document)
    normalizer = _Normalizer(error) if isinstance(error, DocumentNormalizationError) else _Normalizer([_page()])
    store = _Store(error) if isinstance(error, ObjectVerificationError) else _Store()
    service = DocumentNormalizationService(repository, store, normalizer)

    await service.process(
        tenant_id=document.tenant_id,
        document_id=document.id,
        expected_version=5,
    )

    assert repository.completed is None
    assert repository.failed is not None
    assert repository.failed["error_class"] == error_class
    assert "raw" not in str(repository.failed)


@pytest.mark.asyncio
async def test_normalization_timeout_is_persisted_as_safe_failure() -> None:
    document = _processing_document()
    repository = _Repository(document)
    service = DocumentNormalizationService(
        repository,
        _Store(),
        _Normalizer([_page()], delay=0.05),
        timeout_seconds=0.001,
    )

    await service.process(
        tenant_id=document.tenant_id,
        document_id=document.id,
        expected_version=5,
    )

    assert repository.failed is not None
    assert repository.failed["error_class"] == "normalization_timeout"


@pytest.mark.asyncio
async def test_unexpected_normalizer_error_is_persisted_then_reraised() -> None:
    document = _processing_document()
    repository = _Repository(document)
    service = DocumentNormalizationService(
        repository,
        _Store(),
        _Normalizer(RuntimeError("unexpected synthetic failure")),
    )

    with pytest.raises(RuntimeError, match="unexpected synthetic failure"):
        await service.process(
            tenant_id=document.tenant_id,
            document_id=document.id,
            expected_version=5,
        )

    assert repository.failed is not None
    assert repository.failed["error_class"] == "normalization_worker_internal_error"
