"""Transactional PostgreSQL state for document malware scans."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.documents.repository import DocumentNotFound
from app.documents.scanning import MalwareScanOutcome, MalwareScanResult

_GET_DOCUMENT_FOR_UPDATE = """
SELECT * FROM document_registry
WHERE tenant_id = $1 AND id = $2
FOR UPDATE
"""

_NEXT_ATTEMPT = """
SELECT COALESCE(MAX(attempt), 0) + 1
FROM document_scan_run
WHERE tenant_id = $1 AND document_id = $2
"""

_INSERT_RUN = """
INSERT INTO document_scan_run (
    id, tenant_id, document_id, attempt, status, started_at
) VALUES ($1, $2, $3, $4, 'running', $5)
"""

_UPDATE_DOCUMENT_SCAN = """
UPDATE document_registry
SET state = $4, version = $5, updated_at = $6,
    active_processing_run_id = $7,
    processing_object_key = COALESCE($8, processing_object_key)
WHERE tenant_id = $1 AND id = $2 AND version = $3
RETURNING *
"""

_COMPLETE_RUN = """
UPDATE document_scan_run
SET status = 'completed', outcome = $4, engine = $5, engine_version = $6,
    signature_version = $7, threat_name = $8, completed_at = $9
WHERE tenant_id = $1 AND document_id = $2 AND id = $3 AND status = 'running'
"""

_FAIL_RUN = """
UPDATE document_scan_run
SET status = 'failed', error_class = $4, completed_at = $5
WHERE tenant_id = $1 AND document_id = $2 AND id = $3 AND status = 'running'
"""

_INSERT_EVENT = """
INSERT INTO document_outbox (
    event_id, tenant_id, aggregate_id, event_type, event_version, producer,
    correlation_id, data_classification, idempotency_key, artifact_refs, payload
) VALUES ($1, $2, $3, $4, 1, 'document-scanner', $5, 'restricted', $6, $7, $8)
ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
"""


@dataclass(frozen=True)
class DocumentScanRun:
    id: UUID
    tenant_id: UUID
    document_id: UUID
    attempt: int
    started_at: datetime


@dataclass(frozen=True)
class ScanStartResult:
    document: DocumentRegistryEntry
    run: DocumentScanRun


class PostgresDocumentScanRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def start(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        expected_version: int,
    ) -> ScanStartResult:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('app.tenant_id', $1, true)", str(tenant_id)
                )
                row = await connection.fetchrow(
                    _GET_DOCUMENT_FOR_UPDATE, tenant_id, document_id
                )
                if row is None:
                    raise DocumentNotFound("Document not found")
                document = DocumentRegistryEntry.model_validate(dict(row))
                document.transition(DocumentState.SCANNING, expected_version=expected_version)
                attempt = int(
                    await connection.fetchval(_NEXT_ATTEMPT, tenant_id, document_id)
                )
                run = DocumentScanRun(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    document_id=document_id,
                    attempt=attempt,
                    started_at=datetime.now(UTC),
                )
                await connection.execute(
                    _INSERT_RUN,
                    run.id,
                    tenant_id,
                    document_id,
                    attempt,
                    run.started_at,
                )
                document.active_processing_run_id = run.id
                updated = await connection.fetchrow(
                    _UPDATE_DOCUMENT_SCAN,
                    tenant_id,
                    document_id,
                    expected_version,
                    document.state.value,
                    document.version,
                    document.updated_at,
                    run.id,
                    None,
                )
                if updated is None:
                    raise RuntimeError("Concurrent scan start was not persisted")
                await self._insert_event(
                    connection,
                    document_id=document_id,
                    tenant_id=tenant_id,
                    run_id=run.id,
                    event_type="DocumentScanStarted.v1",
                    document_version=document.version,
                    outcome=None,
                )
                return ScanStartResult(DocumentRegistryEntry.model_validate(dict(updated)), run)

    async def complete(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        run_id: UUID,
        expected_version: int,
        result: MalwareScanResult,
        processing_object_key: str | None,
    ) -> DocumentRegistryEntry:
        if result.outcome is MalwareScanOutcome.CLEAN:
            expected_prefix = f"clinical-processing/{tenant_id}/{document_id}/"
            if not processing_object_key or not processing_object_key.startswith(expected_prefix):
                raise ValueError("Clean scan requires a scoped processing object")
            next_state = DocumentState.SCAN_PASSED
        else:
            if processing_object_key is not None:
                raise ValueError("Infected document cannot receive a processing object")
            next_state = DocumentState.SCAN_REJECTED

        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('app.tenant_id', $1, true)", str(tenant_id)
                )
                row = await connection.fetchrow(
                    _GET_DOCUMENT_FOR_UPDATE, tenant_id, document_id
                )
                if row is None:
                    raise DocumentNotFound("Document not found")
                document = DocumentRegistryEntry.model_validate(dict(row))
                if document.active_processing_run_id != run_id:
                    raise ValueError("Scan run is not active for this document")
                document.transition(next_state, expected_version=expected_version)
                now = datetime.now(UTC)
                await connection.execute(
                    _COMPLETE_RUN,
                    tenant_id,
                    document_id,
                    run_id,
                    result.outcome.value,
                    result.engine,
                    result.engine_version,
                    result.signature_version,
                    result.threat_name,
                    now,
                )
                document.processing_object_key = processing_object_key
                updated = await connection.fetchrow(
                    _UPDATE_DOCUMENT_SCAN,
                    tenant_id,
                    document_id,
                    expected_version,
                    document.state.value,
                    document.version,
                    document.updated_at,
                    run_id,
                    processing_object_key,
                )
                if updated is None:
                    raise RuntimeError("Concurrent scan completion was not persisted")
                await self._insert_event(
                    connection,
                    document_id=document_id,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    event_type="DocumentScanCompleted.v1",
                    document_version=document.version,
                    outcome=result.outcome.value,
                )
                return DocumentRegistryEntry.model_validate(dict(updated))

    async def fail(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        run_id: UUID,
        expected_version: int,
        error_class: str,
    ) -> DocumentRegistryEntry:
        if not error_class or len(error_class) > 128 or not error_class.replace("_", "").isalnum():
            raise ValueError("Scan error class is invalid")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('app.tenant_id', $1, true)", str(tenant_id)
                )
                row = await connection.fetchrow(
                    _GET_DOCUMENT_FOR_UPDATE, tenant_id, document_id
                )
                if row is None:
                    raise DocumentNotFound("Document not found")
                document = DocumentRegistryEntry.model_validate(dict(row))
                if document.active_processing_run_id != run_id:
                    raise ValueError("Scan run is not active for this document")
                document.transition(
                    DocumentState.PROCESSING_FAILED,
                    expected_version=expected_version,
                )
                now = datetime.now(UTC)
                await connection.execute(
                    _FAIL_RUN,
                    tenant_id,
                    document_id,
                    run_id,
                    error_class,
                    now,
                )
                updated = await connection.fetchrow(
                    _UPDATE_DOCUMENT_SCAN,
                    tenant_id,
                    document_id,
                    expected_version,
                    document.state.value,
                    document.version,
                    document.updated_at,
                    run_id,
                    None,
                )
                if updated is None:
                    raise RuntimeError("Concurrent scan failure was not persisted")
                await self._insert_event(
                    connection,
                    document_id=document_id,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    event_type="DocumentScanFailed.v1",
                    document_version=document.version,
                    outcome=None,
                )
                return DocumentRegistryEntry.model_validate(dict(updated))

    @staticmethod
    async def _insert_event(
        connection: Any,
        *,
        document_id: UUID,
        tenant_id: UUID,
        run_id: UUID,
        event_type: str,
        document_version: int,
        outcome: str | None,
    ) -> None:
        payload: dict[str, object] = {
            "document_version": document_version,
            "processing_run_id": str(run_id),
        }
        if outcome is not None:
            payload["outcome"] = outcome
        await connection.execute(
            _INSERT_EVENT,
            uuid4(),
            tenant_id,
            document_id,
            event_type,
            run_id,
            f"{document_id}:{event_type}:{document_version}",
            json.dumps([]),
            json.dumps(payload),
        )
