"""Durable extraction run and candidate projection tests."""

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any
from uuid import uuid4

import pytest

from app.documents.extraction import PrescriptionRulesExtractor
from app.documents.extraction_repository import PostgresDocumentExtractionRepository
from app.documents.ocr_artifact import DocumentOcrArtifact
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
        refs: list[dict[str, Any]],
        attempt: int = 1,
    ) -> None:
        self.rows = rows
        self.refs = refs
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
        return self.refs

    async def fetchval(self, query: str, *args: Any) -> int:
        self.executions.append((query, args))
        return self.attempt


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def acquire(self) -> _Context:
        return _Context(self.connection)


def _document(version: int = 9) -> DocumentRegistryEntry:
    return DocumentRegistryEntry(
        tenant_id=uuid4(),
        facility_id=uuid4(),
        patient_id=uuid4(),
        encounter_id=uuid4(),
        uploader_actor_id=uuid4(),
        purpose="treatment",
        consent_reference=str(uuid4()),
        original_filename="synthetic.png",
        declared_document_class="prescription",
        declared_mime="image/png",
        declared_size_bytes=16,
        idempotency_key="extraction-repository-test",
        state=DocumentState.PROCESSING,
        version=version,
        source_checksum_sha256="a" * 64,
        active_ocr_run_id=uuid4(),
    )


def _artifact(document: DocumentRegistryEntry, artifact_id=None) -> DocumentOcrArtifact:
    page_artifact_id = uuid4()
    artifact = DocumentOcrArtifact.from_result(
        tenant_id=document.tenant_id,
        document_id=document.id,
        page_artifact_id=page_artifact_id,
        ocr_run_id=document.active_ocr_run_id,
        page_number=1,
        width=300,
        height=100,
        source_checksum_sha256="a" * 64,
        page_checksum_sha256="b" * 64,
        preprocessing_version="normalize.v1",
        result=OCRResult(
            text="Tab Metformin 500 mg",
            regions=[
                OCRRegion(
                    text="Tab Metformin 500 mg",
                    confidence=0.9,
                    bbox=(1, 2, 250, 30),
                )
            ],
            confidence=0.9,
            provider="fixture",
            model_version="fixture-v1",
            language_pack_version="fixture-en-v1",
            duration_ms=1,
        ),
    )
    if artifact_id is not None:
        artifact = artifact.model_copy(update={"artifact_id": artifact_id})
    return artifact


def _run(document: DocumentRegistryEntry, run_id, attempt: int = 1) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "id": run_id,
        "tenant_id": document.tenant_id,
        "document_id": document.id,
        "ocr_run_id": document.active_ocr_run_id,
        "attempt": attempt,
        "parser_version": "prescription-rules.v1",
        "schema_version": "DocumentExtractionDraft.v1",
        "status": "running",
        "started_at": now,
        "lease_expires_at": now + timedelta(minutes=2),
    }


@pytest.mark.asyncio
async def test_start_creates_leased_run_from_completed_ocr_artifact_refs() -> None:
    document = _document()
    artifact_id = uuid4()
    processing = document.model_copy(update={"version": 10})
    connection = _Connection(
        [document.model_dump(), processing.model_dump()],
        [{"artifact_id": artifact_id}],
    )
    repository = PostgresDocumentExtractionRepository(_Pool(connection))

    started = await repository.start(
        tenant_id=document.tenant_id,
        document_id=document.id,
        expected_version=9,
        parser_version="prescription-rules.v1",
    )

    assert started.document.version == 10
    assert started.ocr_artifact_ids == [artifact_id]
    assert started.run.attempt == 1


@pytest.mark.asyncio
async def test_start_reclaims_an_expired_active_run_without_new_attempt() -> None:
    document = _document()
    run_id = uuid4()
    document.active_extraction_run_id = run_id
    artifact_id = uuid4()
    expired_run = _run(document, run_id, attempt=2)
    expired_run["lease_expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    connection = _Connection(
        [document.model_dump(), expired_run],
        [{"artifact_id": artifact_id}],
    )
    repository = PostgresDocumentExtractionRepository(_Pool(connection))

    started = await repository.start(
        tenant_id=document.tenant_id,
        document_id=document.id,
        expected_version=document.version,
        parser_version="prescription-rules.v1",
    )

    assert started.run.id == run_id
    assert started.run.attempt == 2
    assert started.run.lease_expires_at > datetime.now(UTC)
    assert any("UPDATE document_extraction_run" in query for query, _ in connection.executions)
    assert not any("INSERT INTO document_extraction_run" in query for query, _ in connection.executions)


@pytest.mark.asyncio
async def test_start_refuses_to_steal_an_active_lease() -> None:
    document = _document()
    run_id = uuid4()
    document.active_extraction_run_id = run_id
    connection = _Connection(
        [document.model_dump(), _run(document, run_id)],
        [{"artifact_id": uuid4()}],
    )
    repository = PostgresDocumentExtractionRepository(_Pool(connection))

    with pytest.raises(RuntimeError, match="lease is still active"):
        await repository.start(
            tenant_id=document.tenant_id,
            document_id=document.id,
            expected_version=document.version,
            parser_version="prescription-rules.v1",
        )

    assert not any("INSERT INTO document_extraction_run" in query for query, _ in connection.executions)


@pytest.mark.asyncio
async def test_complete_projects_candidates_and_moves_to_review_required() -> None:
    document = _document(version=10)
    run_id = uuid4()
    document.active_extraction_run_id = run_id
    artifact = _artifact(document)
    draft = PrescriptionRulesExtractor().extract([artifact])
    reviewed = document.model_copy(
        update={"state": DocumentState.REVIEW_REQUIRED, "version": 11}
    )
    connection = _Connection(
        [document.model_dump(), _run(document, run_id), reviewed.model_dump()],
        [{"artifact_id": artifact.artifact_id}],
    )
    repository = PostgresDocumentExtractionRepository(_Pool(connection))

    result = await repository.complete(
        tenant_id=document.tenant_id,
        document_id=document.id,
        run_id=run_id,
        expected_version=10,
        draft=draft,
    )

    assert result.state is DocumentState.REVIEW_REQUIRED
    assert result.version == 11
    assert "INSERT INTO document_extraction_candidate" in str(connection.executions)
    event_args = next(
        args for query, args in connection.executions if "INSERT INTO document_outbox" in query
    )
    assert "DocumentProcessingCompleted.v1" in event_args
    assert "Metformin" not in str(event_args)
    assert "Tab Metformin" not in str(event_args)
    assert document.original_filename not in str(event_args)
    assert str(document.patient_id) not in str(event_args)


@pytest.mark.asyncio
async def test_retryable_failure_keeps_document_processing() -> None:
    document = _document(version=10)
    run_id = uuid4()
    document.active_extraction_run_id = run_id
    retrying = document.model_copy(update={"version": 11})
    connection = _Connection(
        [document.model_dump(), _run(document, run_id), retrying.model_dump()],
        [],
    )
    repository = PostgresDocumentExtractionRepository(_Pool(connection), max_attempts=3)

    result = await repository.fail(
        tenant_id=document.tenant_id,
        document_id=document.id,
        run_id=run_id,
        expected_version=10,
        error_class="artifact_store_error",
    )

    assert result.state is DocumentState.PROCESSING
    assert result.version == 11
    assert "DocumentExtractionFailed.v1" in str(connection.executions)


@pytest.mark.asyncio
async def test_last_failure_moves_document_to_processing_failed() -> None:
    document = _document(version=14)
    run_id = uuid4()
    document.active_extraction_run_id = run_id
    failed = document.model_copy(
        update={"state": DocumentState.PROCESSING_FAILED, "version": 15}
    )
    connection = _Connection(
        [document.model_dump(), _run(document, run_id, attempt=3), failed.model_dump()],
        [],
    )
    repository = PostgresDocumentExtractionRepository(_Pool(connection), max_attempts=3)

    result = await repository.fail(
        tenant_id=document.tenant_id,
        document_id=document.id,
        run_id=run_id,
        expected_version=14,
        error_class="parser_error",
    )

    assert result.state is DocumentState.PROCESSING_FAILED
    assert "DocumentExtractionDeadLettered.v1" in str(connection.executions)
