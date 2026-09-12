"""Transactional extraction state, review candidates, and safe events."""

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.documents.extraction import PrescriptionExtractionDraft
from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.documents.repository import DocumentNotFound

_GET_DOCUMENT_FOR_UPDATE = """
SELECT * FROM document_registry
WHERE tenant_id = $1 AND id = $2
FOR UPDATE
"""

_GET_RUN = """
SELECT * FROM document_extraction_run
WHERE tenant_id = $1 AND document_id = $2 AND id = $3
"""

_GET_OCR_REFS = """
SELECT artifact_id
FROM document_ocr_page_ref
WHERE tenant_id = $1 AND document_id = $2 AND ocr_run_id = $3
ORDER BY page_number
"""

_NEXT_ATTEMPT = """
SELECT COALESCE(MAX(attempt), 0) + 1
FROM document_extraction_run
WHERE tenant_id = $1 AND document_id = $2
"""

_INSERT_RUN = """
INSERT INTO document_extraction_run (
    id, tenant_id, document_id, ocr_run_id, attempt, parser_version,
    schema_version, status, started_at, lease_expires_at
) VALUES ($1, $2, $3, $4, $5, $6, $7, 'running', $8, $9)
"""

_RECLAIM_RUN = """
UPDATE document_extraction_run
SET lease_expires_at = $4
WHERE tenant_id = $1 AND document_id = $2 AND id = $3
  AND status = 'running' AND lease_expires_at <= CURRENT_TIMESTAMP
"""

_UPDATE_DOCUMENT = """
UPDATE document_registry
SET state = $4, version = $5, updated_at = $6, active_extraction_run_id = $7
WHERE tenant_id = $1 AND id = $2 AND version = $3
RETURNING *
"""

_COMPLETE_RUN = """
UPDATE document_extraction_run
SET status = 'completed', completed_at = $4
WHERE tenant_id = $1 AND document_id = $2 AND id = $3 AND status = 'running'
"""

_FAIL_RUN = """
UPDATE document_extraction_run
SET status = $4, error_class = $5, completed_at = $6
WHERE tenant_id = $1 AND document_id = $2 AND id = $3 AND status = 'running'
"""

_INSERT_CANDIDATE = """
INSERT INTO document_extraction_candidate (
    candidate_id, tenant_id, document_id, extraction_run_id, draft_id,
    entity_type, normalized_value, unit, source_page_artifact_id,
    source_ocr_artifact_id, source_region_id, source_page_number,
    parser_version, parser_signal, negated, temporality, subject, uncertainty,
    document_statement, clinician_confirmed_current, review_state, version,
    source_page_width, source_page_height, source_bbox, source_polygon
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
    $13, $14, $15, $16, $17, $18, $19, $20, 'unreviewed', 1,
    $21, $22, $23, $24
)
ON CONFLICT (tenant_id, extraction_run_id, candidate_id) DO NOTHING
"""

_INSERT_EVENT = """
INSERT INTO document_outbox (
    event_id, tenant_id, aggregate_id, event_type, event_version, producer,
    correlation_id, data_classification, idempotency_key, artifact_refs, payload
) VALUES ($1, $2, $3, $4, 1, 'document-extraction-worker', $5, 'restricted', $6, $7, $8)
ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
"""


@dataclass(frozen=True)
class DocumentExtractionRun:
    id: UUID
    tenant_id: UUID
    document_id: UUID
    ocr_run_id: UUID
    attempt: int
    parser_version: str
    schema_version: str
    status: str
    started_at: datetime
    lease_expires_at: datetime


@dataclass(frozen=True)
class ExtractionStartResult:
    document: DocumentRegistryEntry
    run: DocumentExtractionRun
    ocr_artifact_ids: list[UUID]


def _run_from_row(row: Any) -> DocumentExtractionRun:
    values = dict(row)
    return DocumentExtractionRun(
        **{field: values[field] for field in DocumentExtractionRun.__dataclass_fields__}
    )


def _valid_error_class(value: str) -> bool:
    return bool(value) and len(value) <= 128 and value.replace("_", "").isalnum()


class PostgresDocumentExtractionRepository:
    def __init__(
        self,
        pool: Any,
        *,
        lease_seconds: int = 60,
        max_attempts: int = 3,
    ) -> None:
        if lease_seconds <= 0 or max_attempts <= 0:
            raise ValueError("Extraction lease and attempt limits must be positive")
        self._pool = pool
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts

    async def start(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        expected_version: int,
        parser_version: str,
    ) -> ExtractionStartResult:
        if not parser_version or len(parser_version) > 64:
            raise ValueError("Extraction parser version is invalid")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                row = await connection.fetchrow(
                    _GET_DOCUMENT_FOR_UPDATE, tenant_id, document_id
                )
                if row is None:
                    raise DocumentNotFound("Document not found")
                document = DocumentRegistryEntry.model_validate(dict(row))
                document._assert_version(expected_version)
                if document.state is not DocumentState.PROCESSING:
                    raise ValueError("Document is not ready for extraction")
                if document.declared_document_class != "prescription":
                    raise ValueError("Document class is not supported for extraction")
                if document.active_ocr_run_id is None:
                    raise ValueError("Document has no completed OCR run")
                ref_rows = await connection.fetch(
                    _GET_OCR_REFS,
                    tenant_id,
                    document_id,
                    document.active_ocr_run_id,
                )
                artifact_ids = [row["artifact_id"] for row in ref_rows]
                if not artifact_ids:
                    raise ValueError("Document has no durable OCR artifacts")

                now = datetime.now(UTC)
                lease_expires_at = now + timedelta(seconds=self._lease_seconds)
                if document.active_extraction_run_id is not None:
                    active_row = await connection.fetchrow(
                        _GET_RUN,
                        tenant_id,
                        document_id,
                        document.active_extraction_run_id,
                    )
                    if active_row is None:
                        raise RuntimeError("Active extraction run is missing")
                    active = _run_from_row(active_row)
                    if active.status == "running":
                        if active.lease_expires_at > now:
                            raise RuntimeError("Extraction run lease is still active")
                        status = await connection.execute(
                            _RECLAIM_RUN,
                            tenant_id,
                            document_id,
                            active.id,
                            lease_expires_at,
                        )
                        if not status.endswith(" 1"):
                            raise RuntimeError("Expired extraction run was not reclaimed")
                        return ExtractionStartResult(
                            document,
                            replace(active, lease_expires_at=lease_expires_at),
                            artifact_ids,
                        )
                    if active.status in {"completed", "dead_letter"}:
                        raise RuntimeError("Extraction run is already terminal")

                attempt = int(
                    await connection.fetchval(_NEXT_ATTEMPT, tenant_id, document_id)
                )
                if attempt > self._max_attempts:
                    raise RuntimeError("Extraction retry budget is exhausted")
                run = DocumentExtractionRun(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    document_id=document_id,
                    ocr_run_id=document.active_ocr_run_id,
                    attempt=attempt,
                    parser_version=parser_version,
                    schema_version="DocumentExtractionDraft.v1",
                    status="running",
                    started_at=now,
                    lease_expires_at=lease_expires_at,
                )
                await connection.execute(
                    _INSERT_RUN,
                    run.id,
                    tenant_id,
                    document_id,
                    run.ocr_run_id,
                    attempt,
                    parser_version,
                    run.schema_version,
                    now,
                    lease_expires_at,
                )
                document.record_processing_progress(expected_version=expected_version)
                document.active_extraction_run_id = run.id
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
                    raise RuntimeError("Concurrent extraction start was not persisted")
                return ExtractionStartResult(
                    DocumentRegistryEntry.model_validate(dict(updated)),
                    run,
                    artifact_ids,
                )

    async def complete(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        run_id: UUID,
        expected_version: int,
        draft: PrescriptionExtractionDraft,
    ) -> DocumentRegistryEntry:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                document, run = await self._locked_document_and_run(
                    connection, tenant_id, document_id, run_id
                )
                if (
                    draft.tenant_id != tenant_id
                    or draft.document_id != document_id
                    or draft.ocr_run_id != run.ocr_run_id
                    or draft.parser_version != run.parser_version
                ):
                    raise ValueError("Extraction draft provenance does not match its run")
                ref_rows = await connection.fetch(
                    _GET_OCR_REFS, tenant_id, document_id, run.ocr_run_id
                )
                artifact_ids = {row["artifact_id"] for row in ref_rows}
                if any(
                    candidate.source.ocr_artifact_id not in artifact_ids
                    for candidate in draft.candidates
                ):
                    raise ValueError("Extraction candidate references unknown OCR evidence")
                for candidate in draft.candidates:
                    await connection.execute(
                        _INSERT_CANDIDATE,
                        candidate.candidate_id,
                        tenant_id,
                        document_id,
                        run_id,
                        draft.draft_id,
                        candidate.entity_type,
                        candidate.normalized_value,
                        candidate.unit,
                        candidate.source.page_artifact_id,
                        candidate.source.ocr_artifact_id,
                        candidate.source.region_id,
                        candidate.source.page_number,
                        candidate.parser_version,
                        candidate.parser_signal,
                        candidate.negated,
                        candidate.temporality,
                        candidate.subject,
                        candidate.uncertainty,
                        candidate.document_statement,
                        candidate.clinician_confirmed_current,
                        candidate.source.page_width,
                        candidate.source.page_height,
                        json.dumps(candidate.source.bbox)
                        if candidate.source.bbox is not None
                        else None,
                        json.dumps(candidate.source.polygon)
                        if candidate.source.polygon is not None
                        else None,
                    )
                status = await connection.execute(
                    _COMPLETE_RUN, tenant_id, document_id, run_id, datetime.now(UTC)
                )
                if not status.endswith(" 1"):
                    raise RuntimeError("Extraction completion was not persisted")
                document.transition(
                    DocumentState.REVIEW_REQUIRED,
                    expected_version=expected_version,
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
                    raise RuntimeError("Concurrent extraction completion was not persisted")
                await self._event(
                    connection,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    run=run,
                    event_type="DocumentProcessingCompleted.v1",
                    document_version=document.version,
                    artifact_refs=[
                        {
                            "artifact_type": "document_extraction_draft",
                            "artifact_id": str(draft.draft_id),
                        }
                    ],
                    extra_payload={"candidate_count": len(draft.candidates)},
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
        if not _valid_error_class(error_class):
            raise ValueError("Extraction error class is invalid")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                document, run = await self._locked_document_and_run(
                    connection, tenant_id, document_id, run_id
                )
                terminal = run.attempt >= self._max_attempts
                if terminal:
                    document.transition(
                        DocumentState.PROCESSING_FAILED,
                        expected_version=expected_version,
                    )
                    run_status = "dead_letter"
                    event_type = "DocumentExtractionDeadLettered.v1"
                else:
                    document.record_processing_progress(expected_version=expected_version)
                    run_status = "failed"
                    event_type = "DocumentExtractionFailed.v1"
                status = await connection.execute(
                    _FAIL_RUN,
                    tenant_id,
                    document_id,
                    run_id,
                    run_status,
                    error_class,
                    datetime.now(UTC),
                )
                if not status.endswith(" 1"):
                    raise RuntimeError("Extraction failure was not persisted")
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
                    raise RuntimeError("Concurrent extraction failure was not persisted")
                await self._event(
                    connection,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    run=run,
                    event_type=event_type,
                    document_version=document.version,
                    artifact_refs=[],
                    extra_payload={
                        "error_class": error_class,
                        "will_retry": not terminal,
                    },
                )
                return DocumentRegistryEntry.model_validate(dict(updated))

    async def _locked_document_and_run(
        self,
        connection: Any,
        tenant_id: UUID,
        document_id: UUID,
        run_id: UUID,
    ) -> tuple[DocumentRegistryEntry, DocumentExtractionRun]:
        row = await connection.fetchrow(_GET_DOCUMENT_FOR_UPDATE, tenant_id, document_id)
        if row is None:
            raise DocumentNotFound("Document not found")
        document = DocumentRegistryEntry.model_validate(dict(row))
        if document.active_extraction_run_id != run_id:
            raise ValueError("Extraction run is not active for this document")
        run_row = await connection.fetchrow(_GET_RUN, tenant_id, document_id, run_id)
        if run_row is None:
            raise RuntimeError("Extraction run is missing")
        run = _run_from_row(run_row)
        if run.status != "running":
            raise ValueError("Extraction run is not running")
        return document, run

    @staticmethod
    async def _set_tenant(connection: Any, tenant_id: UUID) -> None:
        await connection.execute(
            "SELECT set_config('app.tenant_id', $1, true)", str(tenant_id)
        )

    @staticmethod
    async def _event(
        connection: Any,
        *,
        tenant_id: UUID,
        document_id: UUID,
        run: DocumentExtractionRun,
        event_type: str,
        document_version: int,
        artifact_refs: list[dict[str, str]],
        extra_payload: dict[str, object],
    ) -> None:
        payload: dict[str, object] = {
            "document_version": document_version,
            "extraction_run_id": str(run.id),
            "parser_version": run.parser_version,
            "schema_version": run.schema_version,
        }
        payload.update(extra_payload)
        await connection.execute(
            _INSERT_EVENT,
            uuid4(),
            tenant_id,
            document_id,
            event_type,
            run.id,
            f"{document_id}:{event_type}:{document_version}",
            json.dumps(artifact_refs),
            json.dumps(payload),
        )
