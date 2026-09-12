"""Transactional OCR run state and reference-only event persistence."""

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.documents.ocr_artifact import DocumentOcrArtifact
from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.documents.repository import DocumentNotFound
from app.documents.storage import PageArtifact

_GET_DOCUMENT_FOR_UPDATE = """
SELECT * FROM document_registry
WHERE tenant_id = $1 AND id = $2
FOR UPDATE
"""

_GET_RUN = """
SELECT * FROM document_ocr_run
WHERE tenant_id = $1 AND document_id = $2 AND id = $3
"""

_GET_PAGES = """
SELECT id, page_number, object_key, checksum_sha256, mime, width, height,
       preprocessing_version
FROM document_page_artifact
WHERE tenant_id = $1 AND document_id = $2 AND normalization_run_id = $3
ORDER BY page_number
"""

_NEXT_ATTEMPT = """
SELECT COALESCE(MAX(attempt), 0) + 1
FROM document_ocr_run
WHERE tenant_id = $1 AND document_id = $2
"""

_INSERT_RUN = """
INSERT INTO document_ocr_run (
    id, tenant_id, document_id, normalization_run_id, attempt, provider,
    model_version, language_pack_version, schema_version, status, started_at,
    lease_expires_at
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'running', $10, $11)
"""

_RECLAIM_RUN = """
UPDATE document_ocr_run
SET lease_expires_at = $4
WHERE tenant_id = $1 AND document_id = $2 AND id = $3
  AND status = 'running' AND lease_expires_at <= CURRENT_TIMESTAMP
"""

_UPDATE_DOCUMENT = """
UPDATE document_registry
SET state = $4, version = $5, updated_at = $6, active_ocr_run_id = $7
WHERE tenant_id = $1 AND id = $2 AND version = $3
RETURNING *
"""

_COMPLETE_RUN = """
UPDATE document_ocr_run
SET status = 'completed', completed_at = $4
WHERE tenant_id = $1 AND document_id = $2 AND id = $3 AND status = 'running'
"""

_FAIL_RUN = """
UPDATE document_ocr_run
SET status = $4, error_class = $5, completed_at = $6
WHERE tenant_id = $1 AND document_id = $2 AND id = $3 AND status = 'running'
"""

_INSERT_PAGE_REF = """
INSERT INTO document_ocr_page_ref (
    artifact_id, tenant_id, document_id, ocr_run_id, page_artifact_id, page_number
) VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (tenant_id, ocr_run_id, page_artifact_id) DO NOTHING
"""

_INSERT_EVENT = """
INSERT INTO document_outbox (
    event_id, tenant_id, aggregate_id, event_type, event_version, producer,
    correlation_id, data_classification, idempotency_key, artifact_refs, payload
) VALUES ($1, $2, $3, $4, 1, 'document-ocr-worker', $5, 'restricted', $6, $7, $8)
ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
"""


@dataclass(frozen=True)
class DocumentOcrRun:
    id: UUID
    tenant_id: UUID
    document_id: UUID
    normalization_run_id: UUID
    attempt: int
    provider: str
    model_version: str
    language_pack_version: str
    schema_version: str
    status: str
    started_at: datetime
    lease_expires_at: datetime


@dataclass(frozen=True)
class OcrStartResult:
    document: DocumentRegistryEntry
    run: DocumentOcrRun
    pages: list[PageArtifact]


def _run_from_row(row: Any) -> DocumentOcrRun:
    values = dict(row)
    return DocumentOcrRun(
        **{field: values[field] for field in DocumentOcrRun.__dataclass_fields__}
    )


def _valid_error_class(value: str) -> bool:
    return bool(value) and len(value) <= 128 and value.replace("_", "").isalnum()


class PostgresDocumentOcrRepository:
    def __init__(
        self,
        pool: Any,
        *,
        lease_seconds: int = 120,
        max_attempts: int = 3,
    ) -> None:
        if lease_seconds <= 0 or max_attempts <= 0:
            raise ValueError("OCR lease and attempt limits must be positive")
        self._pool = pool
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts

    async def start(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        expected_version: int,
        provider: str,
        model_version: str,
        language_pack_version: str,
    ) -> OcrStartResult:
        for value in (provider, model_version, language_pack_version):
            if not value or len(value) > 128:
                raise ValueError("OCR provider metadata is invalid")
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
                    raise ValueError("Document is not ready for OCR")
                if document.active_normalization_run_id is None:
                    raise ValueError("Document has no normalized page run")
                page_rows = await connection.fetch(
                    _GET_PAGES,
                    tenant_id,
                    document_id,
                    document.active_normalization_run_id,
                )
                pages = [PageArtifact(**dict(page)) for page in page_rows]
                if not pages:
                    raise ValueError("Document has no normalized pages")

                now = datetime.now(UTC)
                lease_expires_at = now + timedelta(seconds=self._lease_seconds)
                if document.active_ocr_run_id is not None:
                    active_row = await connection.fetchrow(
                        _GET_RUN,
                        tenant_id,
                        document_id,
                        document.active_ocr_run_id,
                    )
                    if active_row is None:
                        raise RuntimeError("Active OCR run is missing")
                    active = _run_from_row(active_row)
                    if active.status == "running":
                        if active.lease_expires_at > now:
                            raise RuntimeError("OCR run lease is still active")
                        status = await connection.execute(
                            _RECLAIM_RUN,
                            tenant_id,
                            document_id,
                            active.id,
                            lease_expires_at,
                        )
                        if not status.endswith(" 1"):
                            raise RuntimeError("Expired OCR run was not reclaimed")
                        return OcrStartResult(
                            document,
                            replace(active, lease_expires_at=lease_expires_at),
                            pages,
                        )
                    if active.status in {"completed", "dead_letter"}:
                        raise RuntimeError("OCR run is already terminal")

                attempt = int(
                    await connection.fetchval(_NEXT_ATTEMPT, tenant_id, document_id)
                )
                if attempt > self._max_attempts:
                    raise RuntimeError("OCR retry budget is exhausted")
                run = DocumentOcrRun(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    document_id=document_id,
                    normalization_run_id=document.active_normalization_run_id,
                    attempt=attempt,
                    provider=provider,
                    model_version=model_version,
                    language_pack_version=language_pack_version,
                    schema_version="DocumentOcrArtifact.v1",
                    status="running",
                    started_at=now,
                    lease_expires_at=lease_expires_at,
                )
                await connection.execute(
                    _INSERT_RUN,
                    run.id,
                    tenant_id,
                    document_id,
                    run.normalization_run_id,
                    run.attempt,
                    provider,
                    model_version,
                    language_pack_version,
                    run.schema_version,
                    now,
                    lease_expires_at,
                )
                document.record_processing_progress(expected_version=expected_version)
                document.active_ocr_run_id = run.id
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
                    raise RuntimeError("Concurrent OCR start was not persisted")
                await self._event(
                    connection,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    run=run,
                    event_type="ai.ocr.requested.v1",
                    document_version=document.version,
                    artifact_refs=[],
                    extra_payload={"page_count": len(pages)},
                )
                return OcrStartResult(
                    DocumentRegistryEntry.model_validate(dict(updated)), run, pages
                )

    async def complete(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        run_id: UUID,
        expected_version: int,
        artifacts: list[DocumentOcrArtifact],
    ) -> DocumentRegistryEntry:
        if not artifacts:
            raise ValueError("OCR must persist at least one page artifact")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                document, run = await self._locked_document_and_run(
                    connection, tenant_id, document_id, run_id
                )
                pages = await connection.fetch(
                    _GET_PAGES,
                    tenant_id,
                    document_id,
                    run.normalization_run_id,
                )
                page_by_id = {page["id"]: page for page in pages}
                if {artifact.page_artifact_id for artifact in artifacts} != set(page_by_id):
                    raise ValueError("OCR artifacts do not cover the normalized page set")
                for artifact in artifacts:
                    page = page_by_id[artifact.page_artifact_id]
                    if (
                        artifact.tenant_id != tenant_id
                        or artifact.document_id != document_id
                        or artifact.ocr_run_id != run_id
                        or artifact.page_number != page["page_number"]
                        or artifact.page_checksum_sha256 != page["checksum_sha256"]
                        or artifact.source_checksum_sha256 != document.source_checksum_sha256
                        or artifact.provider != run.provider
                        or artifact.model_version != run.model_version
                        or artifact.language_pack_version != run.language_pack_version
                    ):
                        raise ValueError("OCR artifact provenance does not match its run")
                    await connection.execute(
                        _INSERT_PAGE_REF,
                        artifact.artifact_id,
                        tenant_id,
                        document_id,
                        run_id,
                        artifact.page_artifact_id,
                        artifact.page_number,
                    )
                status = await connection.execute(
                    _COMPLETE_RUN, tenant_id, document_id, run_id, datetime.now(UTC)
                )
                if not status.endswith(" 1"):
                    raise RuntimeError("OCR run completion was not persisted")
                document.record_processing_progress(expected_version=expected_version)
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
                    raise RuntimeError("Concurrent OCR completion was not persisted")
                refs = [
                    {
                        "artifact_type": "document_ocr_artifact",
                        "artifact_id": str(artifact.artifact_id),
                    }
                    for artifact in artifacts
                ]
                await self._event(
                    connection,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    run=run,
                    event_type="ai.ocr.completed.v1",
                    document_version=document.version,
                    artifact_refs=refs,
                    extra_payload={"page_count": len(artifacts)},
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
            raise ValueError("OCR error class is invalid")
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
                    event_type = "DocumentOcrDeadLettered.v1"
                else:
                    document.record_processing_progress(expected_version=expected_version)
                    run_status = "failed"
                    event_type = "DocumentOcrFailed.v1"
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
                    raise RuntimeError("OCR run failure was not persisted")
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
                    raise RuntimeError("Concurrent OCR failure was not persisted")
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
    ) -> tuple[DocumentRegistryEntry, DocumentOcrRun]:
        row = await connection.fetchrow(_GET_DOCUMENT_FOR_UPDATE, tenant_id, document_id)
        if row is None:
            raise DocumentNotFound("Document not found")
        document = DocumentRegistryEntry.model_validate(dict(row))
        if document.active_ocr_run_id != run_id:
            raise ValueError("OCR run is not active for this document")
        run_row = await connection.fetchrow(_GET_RUN, tenant_id, document_id, run_id)
        if run_row is None:
            raise RuntimeError("OCR run is missing")
        run = _run_from_row(run_row)
        if run.status != "running":
            raise ValueError("OCR run is not running")
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
        run: DocumentOcrRun,
        event_type: str,
        document_version: int,
        artifact_refs: list[dict[str, str]],
        extra_payload: dict[str, object],
    ) -> None:
        payload: dict[str, object] = {
            "document_version": document_version,
            "ocr_run_id": str(run.id),
            "provider": run.provider,
            "model_version": run.model_version,
            "language_pack_version": run.language_pack_version,
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
