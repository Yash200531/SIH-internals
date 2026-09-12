"""Durable OCR run, retry, and reference-only outbox tests."""

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any
from uuid import uuid4

import pytest

from app.documents.ocr_artifact import DocumentOcrArtifact
from app.documents.ocr_repository import PostgresDocumentOcrRepository
from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.ocr.base import OCRRegion, OCRResult


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
    def __init__(
        self,
        rows: list[dict[str, Any] | None],
        pages: list[dict[str, Any]],
        attempt: int = 1,
    ) -> None:
        self.rows = rows
        self.pages = pages
        self.attempt = attempt
        self.executions: list[tuple[str, tuple[Any, ...]]] = []

    def transaction(self) -> _Context:
        return _Context(self)

    async def execute(self, query: str, *args: Any) -> str:
        self.executions.append((query, args))
        return "UPDATE 1"

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.executions.append((query, args))
        return self.rows.pop(0)

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.executions.append((query, args))
        return self.pages

    async def fetchval(self, query: str, *args: Any) -> int:
        self.executions.append((query, args))
        return self.attempt


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def acquire(self) -> _Context:
        return _Context(self.connection)


def _document(version: int = 7) -> DocumentRegistryEntry:
    return DocumentRegistryEntry(
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
        idempotency_key="ocr-repository-test",
        state=DocumentState.PROCESSING,
        version=version,
        source_checksum_sha256="a" * 64,
        detected_mime="image/png",
        active_normalization_run_id=uuid4(),
    )


def _page(document: DocumentRegistryEntry) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "page_number": 1,
        "object_key": (
            f"derived/{document.tenant_id}/{document.id}/"
            f"{document.active_normalization_run_id}/pages/0001.png"
        ),
        "checksum_sha256": "b" * 64,
        "mime": "image/png",
        "width": 100,
        "height": 40,
        "preprocessing_version": "normalize.v1",
    }


def _run(document: DocumentRegistryEntry, run_id, *, attempt: int = 1) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "id": run_id,
        "tenant_id": document.tenant_id,
        "document_id": document.id,
        "normalization_run_id": document.active_normalization_run_id,
        "attempt": attempt,
        "provider": "mock",
        "model_version": "mock-ocr-v1",
        "language_pack_version": "synthetic-en-v1",
        "schema_version": "DocumentOcrArtifact.v1",
        "status": "running",
        "started_at": now,
        "lease_expires_at": now + timedelta(minutes=2),
    }


def _artifact(document: DocumentRegistryEntry, page: dict[str, Any], run_id) -> DocumentOcrArtifact:
    return DocumentOcrArtifact.from_result(
        tenant_id=document.tenant_id,
        document_id=document.id,
        page_artifact_id=page["id"],
        ocr_run_id=run_id,
        page_number=1,
        width=100,
        height=40,
        source_checksum_sha256="a" * 64,
        page_checksum_sha256="b" * 64,
        preprocessing_version="normalize.v1",
        result=OCRResult(
            text="raw OCR must stay out of PostgreSQL events",
            regions=[OCRRegion(text="raw OCR must stay out", confidence=None)],
            confidence=None,
            provider="mock",
            model_version="mock-ocr-v1",
            language_pack_version="synthetic-en-v1",
            duration_ms=1,
        ),
    )


@pytest.mark.asyncio
async def test_start_creates_leased_run_and_returns_normalized_pages() -> None:
    document = _document()
    page = _page(document)
    processing = document.model_copy(update={"version": 8})
    connection = _Connection([document.model_dump(), processing.model_dump()], [page])
    repository = PostgresDocumentOcrRepository(_Pool(connection))

    started = await repository.start(
        tenant_id=document.tenant_id,
        document_id=document.id,
        expected_version=7,
        provider="mock",
        model_version="mock-ocr-v1",
        language_pack_version="synthetic-en-v1",
    )

    assert started.document.version == 8
    assert started.run.attempt == 1
    assert started.pages[0].id == page["id"]
    assert "ai.ocr.requested.v1" in str(connection.executions)


@pytest.mark.asyncio
async def test_complete_links_mongo_artifacts_before_reference_only_event() -> None:
    document = _document(version=8)
    run_id = uuid4()
    document.active_ocr_run_id = run_id
    page = _page(document)
    completed = document.model_copy(update={"version": 9})
    connection = _Connection(
        [document.model_dump(), _run(document, run_id), completed.model_dump()],
        [page],
    )
    repository = PostgresDocumentOcrRepository(_Pool(connection))
    artifact = _artifact(document, page, run_id)

    result = await repository.complete(
        tenant_id=document.tenant_id,
        document_id=document.id,
        run_id=run_id,
        expected_version=8,
        artifacts=[artifact],
    )

    assert result.version == 9
    serialized = str(connection.executions)
    assert "INSERT INTO document_ocr_page_ref" in serialized
    assert "ai.ocr.completed.v1" in serialized
    assert "raw OCR must stay out" not in serialized
    assert document.original_filename not in serialized
    assert str(document.patient_id) not in serialized


@pytest.mark.asyncio
async def test_retryable_failure_keeps_document_processing() -> None:
    document = _document(version=8)
    run_id = uuid4()
    document.active_ocr_run_id = run_id
    retrying = document.model_copy(update={"version": 9})
    connection = _Connection(
        [document.model_dump(), _run(document, run_id, attempt=1), retrying.model_dump()],
        [],
    )
    repository = PostgresDocumentOcrRepository(_Pool(connection), max_attempts=3)

    result = await repository.fail(
        tenant_id=document.tenant_id,
        document_id=document.id,
        run_id=run_id,
        expected_version=8,
        error_class="provider_error",
    )

    assert result.state is DocumentState.PROCESSING
    assert result.version == 9
    assert "DocumentOcrFailed.v1" in str(connection.executions)


@pytest.mark.asyncio
async def test_last_failure_moves_document_to_dead_letter_state() -> None:
    document = _document(version=12)
    run_id = uuid4()
    document.active_ocr_run_id = run_id
    failed = document.model_copy(
        update={"state": DocumentState.PROCESSING_FAILED, "version": 13}
    )
    connection = _Connection(
        [document.model_dump(), _run(document, run_id, attempt=3), failed.model_dump()],
        [],
    )
    repository = PostgresDocumentOcrRepository(_Pool(connection), max_attempts=3)

    result = await repository.fail(
        tenant_id=document.tenant_id,
        document_id=document.id,
        run_id=run_id,
        expected_version=12,
        error_class="provider_error",
    )

    assert result.state is DocumentState.PROCESSING_FAILED
    assert "DocumentOcrDeadLettered.v1" in str(connection.executions)


@pytest.mark.asyncio
async def test_expired_run_is_reclaimed_with_same_identity_and_document_version() -> None:
    document = _document(version=8)
    run_id = uuid4()
    document.active_ocr_run_id = run_id
    expired = _run(document, run_id)
    expired["lease_expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    page = _page(document)
    connection = _Connection([document.model_dump(), expired], [page])
    repository = PostgresDocumentOcrRepository(_Pool(connection))

    started = await repository.start(
        tenant_id=document.tenant_id,
        document_id=document.id,
        expected_version=8,
        provider="mock",
        model_version="mock-ocr-v1",
        language_pack_version="synthetic-en-v1",
    )

    assert started.run.id == run_id
    assert started.document.version == 8
    assert "SET lease_expires_at" in str(connection.executions)


@pytest.mark.asyncio
async def test_active_run_lease_prevents_duplicate_worker() -> None:
    document = _document(version=8)
    run_id = uuid4()
    document.active_ocr_run_id = run_id
    connection = _Connection(
        [document.model_dump(), _run(document, run_id)],
        [_page(document)],
    )
    repository = PostgresDocumentOcrRepository(_Pool(connection))

    with pytest.raises(RuntimeError, match="lease is still active"):
        await repository.start(
            tenant_id=document.tenant_id,
            document_id=document.id,
            expected_version=8,
            provider="mock",
            model_version="mock-ocr-v1",
            language_pack_version="synthetic-en-v1",
        )
