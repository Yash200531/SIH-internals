"""End-to-end scan orchestration safety tests with deterministic fakes."""

from uuid import uuid4

import pytest

from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.documents.scan_repository import DocumentScanRun, ScanStartResult
from app.documents.scan_service import DocumentScanService
from app.documents.scanning import (
    MalwareScannerError,
    MalwareScanOutcome,
    MalwareScanResult,
)


def _scanning_document() -> DocumentRegistryEntry:
    document = DocumentRegistryEntry(
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
        idempotency_key="scan-service-test",
        state=DocumentState.SCANNING,
        version=4,
        object_key="quarantine/source",
        source_checksum_sha256="a" * 64,
    )
    return document


class _Repository:
    def __init__(self, document: DocumentRegistryEntry) -> None:
        self.document = document
        self.run = DocumentScanRun(
            id=uuid4(),
            tenant_id=document.tenant_id,
            document_id=document.id,
            attempt=1,
            started_at=document.created_at,
        )
        self.completed: dict[str, object] | None = None
        self.failed: dict[str, object] | None = None

    async def start(self, **_scope: object) -> ScanStartResult:
        return ScanStartResult(self.document, self.run)

    async def complete(self, **values: object) -> DocumentRegistryEntry:
        self.completed = values
        return self.document

    async def fail(self, **values: object) -> DocumentRegistryEntry:
        self.failed = values
        return self.document


class _Store:
    def __init__(self) -> None:
        self.promotions = 0

    async def read_for_scan(self, _document: DocumentRegistryEntry) -> bytes:
        return b"safe"

    async def promote_after_clean_scan(
        self, document: DocumentRegistryEntry, processing_run_id: str
    ) -> str:
        self.promotions += 1
        return (
            f"clinical-processing/{document.tenant_id}/{document.id}/"
            f"{processing_run_id}/source"
        )


class _Scanner:
    def __init__(self, result: MalwareScanResult | Exception) -> None:
        self.result = result

    async def scan(self, _payload: bytes) -> MalwareScanResult:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _result(outcome: MalwareScanOutcome) -> MalwareScanResult:
    return MalwareScanResult(
        outcome=outcome,
        engine="clamav",
        engine_version="1.4.6",
        signature_version="28112",
        threat_name="Eicar-Signature" if outcome is MalwareScanOutcome.INFECTED else None,
    )


@pytest.mark.asyncio
async def test_clean_scan_is_promoted_then_completed() -> None:
    document = _scanning_document()
    repository = _Repository(document)
    store = _Store()
    service = DocumentScanService(repository, store, _Scanner(_result(MalwareScanOutcome.CLEAN)))

    await service.process(
        tenant_id=document.tenant_id,
        document_id=document.id,
        expected_version=3,
    )

    assert store.promotions == 1
    assert repository.completed is not None
    assert str(repository.run.id) in str(repository.completed["processing_object_key"])
    assert repository.failed is None


@pytest.mark.asyncio
async def test_infected_scan_never_promotes_source() -> None:
    document = _scanning_document()
    repository = _Repository(document)
    store = _Store()
    service = DocumentScanService(
        repository,
        store,
        _Scanner(_result(MalwareScanOutcome.INFECTED)),
    )

    await service.process(
        tenant_id=document.tenant_id,
        document_id=document.id,
        expected_version=3,
    )

    assert store.promotions == 0
    assert repository.completed is not None
    assert repository.completed["processing_object_key"] is None


@pytest.mark.asyncio
async def test_scanner_outage_is_persisted_as_safe_failure_class() -> None:
    document = _scanning_document()
    repository = _Repository(document)
    service = DocumentScanService(
        repository,
        _Store(),
        _Scanner(MalwareScannerError("raw engine detail must not persist")),
    )

    await service.process(
        tenant_id=document.tenant_id,
        document_id=document.id,
        expected_version=3,
    )

    assert repository.completed is None
    assert repository.failed is not None
    assert repository.failed["error_class"] == "scanner_error"
    assert "raw engine detail" not in str(repository.failed)


@pytest.mark.asyncio
async def test_unexpected_worker_error_is_persisted_then_reraised() -> None:
    document = _scanning_document()
    repository = _Repository(document)
    service = DocumentScanService(
        repository,
        _Store(),
        _Scanner(RuntimeError("unexpected synthetic failure")),
    )

    with pytest.raises(RuntimeError, match="unexpected synthetic failure"):
        await service.process(
            tenant_id=document.tenant_id,
            document_id=document.id,
            expected_version=3,
        )

    assert repository.failed is not None
    assert repository.failed["error_class"] == "scan_worker_internal_error"
