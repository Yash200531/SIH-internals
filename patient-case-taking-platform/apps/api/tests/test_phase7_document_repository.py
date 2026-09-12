"""Phase 7 PostgreSQL document repository behavior."""

from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Any
from uuid import uuid4

import pytest

from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.documents.repository import (
    DocumentNotFound,
    IdempotencyConflict,
    PostgresDocumentRepository,
)


class _AsyncContext(AbstractAsyncContextManager):
    def __init__(self, value: Any):
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
    def __init__(self, rows: list[dict[str, Any] | None]):
        self.rows = rows
        self.tenant_context: str | None = None
        self.executions: list[tuple[str, tuple[Any, ...]]] = []

    def transaction(self) -> _AsyncContext:
        return _AsyncContext(self)

    async def execute(self, query: str, *args: Any) -> None:
        self.executions.append((query, args))
        if "set_config('app.tenant_id'" in query:
            self.tenant_context = str(args[0])

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.executions.append((query, args))
        return self.rows.pop(0)


class _Pool:
    def __init__(self, connection: _Connection):
        self.connection = connection

    def acquire(self) -> _AsyncContext:
        return _AsyncContext(self.connection)


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


@pytest.mark.asyncio
async def test_create_sets_transaction_local_tenant_context() -> None:
    document = _document()
    connection = _Connection([document.model_dump()])
    repository = PostgresDocumentRepository(_Pool(connection))

    result = await repository.create(document)

    assert result.created is True
    assert result.document == document
    assert connection.tenant_context == str(document.tenant_id)


@pytest.mark.asyncio
async def test_create_replays_an_identical_idempotent_registration() -> None:
    document = _document()
    connection = _Connection([None, document.model_dump()])
    repository = PostgresDocumentRepository(_Pool(connection))

    result = await repository.create(document)

    assert result.created is False
    assert result.document == document


@pytest.mark.asyncio
async def test_create_rejects_conflicting_idempotency_key_reuse() -> None:
    document = _document()
    existing = document.model_copy(update={"original_filename": "different.jpg"})
    connection = _Connection([None, existing.model_dump()])
    repository = PostgresDocumentRepository(_Pool(connection))

    with pytest.raises(IdempotencyConflict):
        await repository.create(document)


@pytest.mark.asyncio
async def test_finalize_moves_verified_upload_to_quarantine_and_writes_safe_outbox() -> None:
    document = _document()
    updated = document.model_copy(
        update={
            "state": DocumentState.QUARANTINED,
            "version": 3,
            "object_key": f"quarantine/{document.tenant_id}/{document.id}/source",
            "source_checksum_sha256": "a" * 64,
            "detected_mime": "image/jpeg",
        }
    )
    connection = _Connection([document.model_dump(), updated.model_dump()])
    repository = PostgresDocumentRepository(_Pool(connection))

    result = await repository.finalize_upload(
        tenant_id=document.tenant_id,
        document_id=document.id,
        expected_version=1,
        object_key=updated.object_key or "",
        checksum_sha256="a" * 64,
        detected_mime="image/jpeg",
    )

    assert result.state is DocumentState.QUARANTINED
    assert result.version == 3
    outbox_query, outbox_args = connection.executions[-1]
    assert "INSERT INTO document_outbox" in outbox_query
    assert "DocumentUploaded.v1" in outbox_args
    assert document.original_filename not in str(outbox_args)
    assert str(document.patient_id) not in str(outbox_args)


@pytest.mark.asyncio
async def test_finalize_fails_closed_when_document_is_not_visible_to_tenant() -> None:
    document = _document()
    connection = _Connection([None])
    repository = PostgresDocumentRepository(_Pool(connection))

    with pytest.raises(DocumentNotFound):
        await repository.finalize_upload(
            tenant_id=document.tenant_id,
            document_id=document.id,
            expected_version=1,
            object_key=f"quarantine/{document.tenant_id}/{document.id}/source",
            checksum_sha256="a" * 64,
            detected_mime="image/jpeg",
        )

    assert all("INSERT INTO document_outbox" not in query for query, _ in connection.executions)


@pytest.mark.asyncio
async def test_get_returns_only_the_document_visible_in_tenant_context() -> None:
    document = _document()
    connection = _Connection([document.model_dump()])
    repository = PostgresDocumentRepository(_Pool(connection))

    result = await repository.get(document.tenant_id, document.id)

    assert result == document
    assert connection.tenant_context == str(document.tenant_id)


@pytest.mark.asyncio
async def test_get_does_not_distinguish_missing_from_tenant_hidden_document() -> None:
    document = _document()
    repository = PostgresDocumentRepository(_Pool(_Connection([None])))

    with pytest.raises(DocumentNotFound, match="not found"):
        await repository.get(document.tenant_id, document.id)


@pytest.mark.asyncio
async def test_cancel_uses_optimistic_concurrency_and_persists_state() -> None:
    document = _document()
    cancelled = document.model_copy(update={"state": DocumentState.CANCELLED, "version": 2})
    connection = _Connection([document.model_dump(), cancelled.model_dump()])
    repository = PostgresDocumentRepository(_Pool(connection))

    result = await repository.cancel(
        tenant_id=document.tenant_id,
        document_id=document.id,
        expected_version=1,
    )

    assert result.state is DocumentState.CANCELLED
    assert result.version == 2
    update_query, update_args = connection.executions[-1]
    assert "UPDATE document_registry" in update_query
    assert DocumentState.CANCELLED.value in update_args
