"""Durable malware-scan state and outbox transaction tests."""

from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Any
from uuid import uuid4

import pytest

from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.documents.scan_repository import PostgresDocumentScanRepository
from app.documents.scanning import MalwareScanOutcome, MalwareScanResult


class _Context(AbstractAsyncContextManager):
    def __init__(self, value: Any) -> None:
        self.value = value

    async def __aenter__(self) -> Any:
        return self.value

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class _Connection:
    def __init__(self, rows: list[dict[str, Any] | None]) -> None:
        self.rows = rows
        self.executions: list[tuple[str, tuple[Any, ...]]] = []

    def transaction(self) -> _Context:
        return _Context(self)

    async def execute(self, query: str, *args: Any) -> None:
        self.executions.append((query, args))

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.executions.append((query, args))
        return self.rows.pop(0)

    async def fetchval(self, query: str, *args: Any) -> int:
        self.executions.append((query, args))
        return 1


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def acquire(self) -> _Context:
        return _Context(self.connection)


def _quarantined_document() -> DocumentRegistryEntry:
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
        declared_size_bytes=16,
        idempotency_key="scan-repository-test",
    )
    document.attach_upload(
        object_key=f"quarantine/{document.tenant_id}/{document.id}/source",
        checksum_sha256="a" * 64,
        detected_mime="image/jpeg",
        expected_version=1,
    )
    document.transition(DocumentState.QUARANTINED, expected_version=2)
    return document


@pytest.mark.asyncio
async def test_start_scan_atomically_moves_registry_and_records_run() -> None:
    document = _quarantined_document()
    scanning = document.model_copy(update={"state": DocumentState.SCANNING, "version": 4})
    connection = _Connection([document.model_dump(), scanning.model_dump()])
    repository = PostgresDocumentScanRepository(_Pool(connection))

    started = await repository.start(
        tenant_id=document.tenant_id,
        document_id=document.id,
        expected_version=3,
    )

    assert started.document.state is DocumentState.SCANNING
    assert started.document.version == 4
    assert started.run.document_id == document.id
    serialized = str(connection.executions)
    assert "INSERT INTO document_scan_run" in serialized
    assert "DocumentScanStarted.v1" in serialized
    assert document.original_filename not in serialized
    assert str(document.patient_id) not in serialized


@pytest.mark.asyncio
async def test_clean_scan_promotes_only_reference_and_marks_scan_passed() -> None:
    document = _quarantined_document().model_copy(
        update={"state": DocumentState.SCANNING, "version": 4}
    )
    run_id = uuid4()
    document = document.model_copy(update={"active_processing_run_id": run_id})
    passed = document.model_copy(
        update={
            "state": DocumentState.SCAN_PASSED,
            "version": 5,
            "processing_object_key": f"clinical-processing/{document.tenant_id}/{document.id}/source",
        }
    )
    connection = _Connection([document.model_dump(), passed.model_dump()])
    repository = PostgresDocumentScanRepository(_Pool(connection))
    result = MalwareScanResult(
        outcome=MalwareScanOutcome.CLEAN,
        engine="clamav",
        engine_version="1.4.6",
        signature_version="28112",
    )

    completed = await repository.complete(
        tenant_id=document.tenant_id,
        document_id=document.id,
        run_id=run_id,
        expected_version=4,
        result=result,
        processing_object_key=passed.processing_object_key,
    )

    assert completed.state is DocumentState.SCAN_PASSED
    serialized = str(connection.executions)
    assert "DocumentScanCompleted.v1" in serialized
    assert "clinical-processing/" in serialized


@pytest.mark.asyncio
async def test_scanner_error_keeps_source_out_of_processing_and_records_safe_class() -> None:
    document = _quarantined_document().model_copy(
        update={"state": DocumentState.SCANNING, "version": 4}
    )
    run_id = uuid4()
    document = document.model_copy(update={"active_processing_run_id": run_id})
    failed = document.model_copy(
        update={"state": DocumentState.PROCESSING_FAILED, "version": 5}
    )
    connection = _Connection([document.model_dump(), failed.model_dump()])
    repository = PostgresDocumentScanRepository(_Pool(connection))

    result = await repository.fail(
        tenant_id=document.tenant_id,
        document_id=document.id,
        run_id=run_id,
        expected_version=4,
        error_class="scanner_unavailable",
    )

    assert result.state is DocumentState.PROCESSING_FAILED
    assert result.processing_object_key is None
    serialized = str(connection.executions)
    assert "DocumentScanFailed.v1" in serialized
    assert "scanner_unavailable" in serialized


@pytest.mark.asyncio
async def test_scan_failure_rejects_unbounded_error_detail() -> None:
    repository = PostgresDocumentScanRepository(_Pool(_Connection([])))

    with pytest.raises(ValueError, match="error class"):
        await repository.fail(
            tenant_id=uuid4(),
            document_id=uuid4(),
            run_id=uuid4(),
            expected_version=4,
            error_class="patient name leaked in raw scanner error",
        )
