"""Durable normalized-page transaction tests."""

from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Any
from uuid import uuid4

import pytest

from app.documents.normalization_repository import PostgresDocumentNormalizationRepository
from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.documents.storage import StoredPage


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


def _document(state: DocumentState, version: int) -> DocumentRegistryEntry:
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
        declared_size_bytes=16,
        idempotency_key="normalization-repository-test",
        state=state,
        version=version,
        processing_object_key="clinical-processing/tenant/document/run/source",
    )


@pytest.mark.asyncio
async def test_start_normalization_moves_scan_passed_document_to_processing() -> None:
    document = _document(DocumentState.SCAN_PASSED, 5)
    processing = document.model_copy(update={"state": DocumentState.PROCESSING, "version": 6})
    connection = _Connection([document.model_dump(), processing.model_dump()])
    repository = PostgresDocumentNormalizationRepository(_Pool(connection))

    started = await repository.start(
        tenant_id=document.tenant_id,
        document_id=document.id,
        expected_version=5,
        preprocessing_version="normalize.v1",
    )

    assert started.document.state is DocumentState.PROCESSING
    assert started.run.preprocessing_version == "normalize.v1"
    assert "DocumentNormalizationStarted.v1" in str(connection.executions)


@pytest.mark.asyncio
async def test_complete_persists_page_refs_before_reference_only_event() -> None:
    run_id = uuid4()
    document = _document(DocumentState.PROCESSING, 6).model_copy(
        update={"active_normalization_run_id": run_id}
    )
    completed = document.model_copy(update={"version": 7})
    page = StoredPage(
        page_number=1,
        object_key=f"derived/{document.tenant_id}/{document.id}/{run_id}/pages/0001.png",
        checksum_sha256="a" * 64,
        mime="image/png",
        width=100,
        height=200,
        preprocessing_version="normalize.v1",
        operations=("metadata_strip", "lossless_png"),
    )
    connection = _Connection([document.model_dump(), completed.model_dump()])
    repository = PostgresDocumentNormalizationRepository(_Pool(connection))

    result = await repository.complete(
        tenant_id=document.tenant_id,
        document_id=document.id,
        run_id=run_id,
        expected_version=6,
        pages=[page],
    )

    assert result.version == 7
    serialized = str(connection.executions)
    assert "INSERT INTO document_page_artifact" in serialized
    assert "DocumentPagesNormalized.v1" in serialized
    assert document.original_filename not in serialized
    assert str(document.patient_id) not in serialized
