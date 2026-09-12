"""Transactional PostgreSQL state for normalized document page artifacts."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.documents.repository import DocumentNotFound
from app.documents.storage import StoredPage

_GET_DOCUMENT_FOR_UPDATE = """
SELECT * FROM document_registry
WHERE tenant_id = $1 AND id = $2
FOR UPDATE
"""

_NEXT_ATTEMPT = """
SELECT COALESCE(MAX(attempt), 0) + 1
FROM document_normalization_run
WHERE tenant_id = $1 AND document_id = $2
"""

_INSERT_RUN = """
INSERT INTO document_normalization_run (
    id, tenant_id, document_id, attempt, preprocessing_version, status, started_at
) VALUES ($1, $2, $3, $4, $5, 'running', $6)
"""

_UPDATE_DOCUMENT = """
UPDATE document_registry
SET state = $4, version = $5, updated_at = $6, active_normalization_run_id = $7
WHERE tenant_id = $1 AND id = $2 AND version = $3
RETURNING *
"""

_COMPLETE_RUN = """
UPDATE document_normalization_run
SET status = 'completed', completed_at = $4
WHERE tenant_id = $1 AND document_id = $2 AND id = $3 AND status = 'running'
"""

_FAIL_RUN = """
UPDATE document_normalization_run
SET status = 'failed', error_class = $4, completed_at = $5
WHERE tenant_id = $1 AND document_id = $2 AND id = $3 AND status = 'running'
"""

_INSERT_PAGE = """
INSERT INTO document_page_artifact (
    id, tenant_id, document_id, normalization_run_id, page_number,
    object_key, checksum_sha256, mime, width, height,
    preprocessing_version, operations
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
"""

_INSERT_EVENT = """
INSERT INTO document_outbox (
    event_id, tenant_id, aggregate_id, event_type, event_version, producer,
    correlation_id, data_classification, idempotency_key, artifact_refs, payload
) VALUES ($1, $2, $3, $4, 1, 'document-normalizer', $5, 'restricted', $6, $7, $8)
ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
"""


@dataclass(frozen=True)
class DocumentNormalizationRun:
    id: UUID
    tenant_id: UUID
    document_id: UUID
    attempt: int
    preprocessing_version: str
    started_at: datetime


@dataclass(frozen=True)
class NormalizationStartResult:
    document: DocumentRegistryEntry
    run: DocumentNormalizationRun


class PostgresDocumentNormalizationRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def start(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        expected_version: int,
        preprocessing_version: str,
    ) -> NormalizationStartResult:
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
                document.transition(DocumentState.PROCESSING, expected_version=expected_version)
                attempt = int(
                    await connection.fetchval(_NEXT_ATTEMPT, tenant_id, document_id)
                )
                run = DocumentNormalizationRun(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    document_id=document_id,
                    attempt=attempt,
                    preprocessing_version=preprocessing_version,
                    started_at=datetime.now(UTC),
                )
                await connection.execute(
                    _INSERT_RUN,
                    run.id,
                    tenant_id,
                    document_id,
                    attempt,
                    preprocessing_version,
                    run.started_at,
                )
                document.active_normalization_run_id = run.id
                updated = await connection.fetchrow(
                    _UPDATE_DOCUMENT,
                    tenant_id,
                    document_id,
                    expected_version,
                    document.state.value,
                    document.version,
                    document.updated_at,
                    run.id,
                )
                if updated is None:
                    raise RuntimeError("Concurrent normalization start was not persisted")
                await self._event(
                    connection,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    run_id=run.id,
                    event_type="DocumentNormalizationStarted.v1",
                    version=document.version,
                    artifact_refs=[],
                    payload={"preprocessing_version": preprocessing_version},
                )
                return NormalizationStartResult(
                    DocumentRegistryEntry.model_validate(dict(updated)), run
                )

    async def complete(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        run_id: UUID,
        expected_version: int,
        pages: list[StoredPage],
    ) -> DocumentRegistryEntry:
        if not pages:
            raise ValueError("Normalization must produce at least one page")
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
                if document.active_normalization_run_id != run_id:
                    raise ValueError("Normalization run is not active for this document")
                document.record_processing_progress(expected_version=expected_version)
                refs: list[dict[str, str]] = []
                for page in pages:
                    page_id = uuid4()
                    await connection.execute(
                        _INSERT_PAGE,
                        page_id,
                        tenant_id,
                        document_id,
                        run_id,
                        page.page_number,
                        page.object_key,
                        page.checksum_sha256,
                        page.mime,
                        page.width,
                        page.height,
                        page.preprocessing_version,
                        json.dumps(page.operations),
                    )
                    refs.append(
                        {"artifact_type": "normalized_page", "artifact_id": str(page_id)}
                    )
                await connection.execute(
                    _COMPLETE_RUN,
                    tenant_id,
                    document_id,
                    run_id,
                    datetime.now(UTC),
                )
                updated = await connection.fetchrow(
                    _UPDATE_DOCUMENT,
                    tenant_id,
                    document_id,
                    expected_version,
                    document.state.value,
                    document.version,
                    document.updated_at,
                    run_id,
                )
                if updated is None:
                    raise RuntimeError("Concurrent normalization completion was not persisted")
                await self._event(
                    connection,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    run_id=run_id,
                    event_type="DocumentPagesNormalized.v1",
                    version=document.version,
                    artifact_refs=refs,
                    payload={"page_count": len(pages)},
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
            raise ValueError("Normalization error class is invalid")
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
                if document.active_normalization_run_id != run_id:
                    raise ValueError("Normalization run is not active for this document")
                document.transition(
                    DocumentState.PROCESSING_FAILED,
                    expected_version=expected_version,
                )
                now = datetime.now(UTC)
                await connection.execute(
                    _FAIL_RUN, tenant_id, document_id, run_id, error_class, now
                )
                updated = await connection.fetchrow(
                    _UPDATE_DOCUMENT,
                    tenant_id,
                    document_id,
                    expected_version,
                    document.state.value,
                    document.version,
                    document.updated_at,
                    run_id,
                )
                if updated is None:
                    raise RuntimeError("Concurrent normalization failure was not persisted")
                await self._event(
                    connection,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    run_id=run_id,
                    event_type="DocumentNormalizationFailed.v1",
                    version=document.version,
                    artifact_refs=[],
                    payload={"error_class": error_class},
                )
                return DocumentRegistryEntry.model_validate(dict(updated))

    @staticmethod
    async def _event(
        connection: Any,
        *,
        tenant_id: UUID,
        document_id: UUID,
        run_id: UUID,
        event_type: str,
        version: int,
        artifact_refs: list[dict[str, str]],
        payload: dict[str, object],
    ) -> None:
        await connection.execute(
            _INSERT_EVENT,
            uuid4(),
            tenant_id,
            document_id,
            event_type,
            run_id,
            f"{document_id}:{event_type}:{version}",
            json.dumps(artifact_refs),
            json.dumps({"document_version": version, "run_id": str(run_id)} | payload),
        )
