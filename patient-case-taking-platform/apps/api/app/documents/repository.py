"""PostgreSQL persistence for the Phase 7 document registry."""

import json
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from app.documents.registry import DocumentRegistryEntry, DocumentState

_INSERT_DOCUMENT = """
INSERT INTO document_registry (
    id, tenant_id, facility_id, patient_id, encounter_id, uploader_actor_id,
    purpose, consent_reference, original_filename, declared_mime,
    declared_size_bytes, idempotency_key, upload_expires_at, state, version,
    created_at, updated_at, declared_document_class
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18
)
ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
RETURNING *
"""

_GET_BY_IDEMPOTENCY_KEY = """
SELECT * FROM document_registry
WHERE tenant_id = $1 AND idempotency_key = $2
"""

_GET_BY_ID = """
SELECT * FROM document_registry
WHERE tenant_id = $1 AND id = $2
"""

_GET_FOR_UPDATE = """
SELECT * FROM document_registry
WHERE tenant_id = $1 AND id = $2
FOR UPDATE
"""

_LIST_FOR_PATIENT = """
SELECT * FROM document_registry
WHERE tenant_id = $1
  AND patient_id = $2
  AND facility_id = ANY($3::UUID[])
ORDER BY created_at DESC, id
LIMIT $4
"""

_FINALIZE_UPLOAD = """
UPDATE document_registry
SET state = $4, object_key = $5, source_checksum_sha256 = $6,
    detected_mime = $7, version = $8, updated_at = $9
WHERE tenant_id = $1 AND id = $2 AND version = $3
RETURNING *
"""

_UPDATE_STATE = """
UPDATE document_registry
SET state = $4, version = $5, updated_at = $6
WHERE tenant_id = $1 AND id = $2 AND version = $3
RETURNING *
"""

_INSERT_OUTBOX_EVENT = """
INSERT INTO document_outbox (
    event_id, tenant_id, aggregate_id, event_type, event_version, producer,
    correlation_id, data_classification, idempotency_key, artifact_refs, payload
) VALUES ($1, $2, $3, $4, 1, 'document-registry', $3, 'restricted', $5, $6, $7)
"""

_INITIATION_FIELDS = (
    "tenant_id",
    "facility_id",
    "patient_id",
    "encounter_id",
    "uploader_actor_id",
    "purpose",
    "consent_reference",
    "original_filename",
    "declared_document_class",
    "declared_mime",
    "declared_size_bytes",
    "idempotency_key",
)


class IdempotencyConflict(ValueError):
    """Raised when a key is reused for a different document registration."""


class DocumentNotFound(LookupError):
    """Raised when row-level security hides or cannot find a document."""


@dataclass(frozen=True)
class DocumentCreateResult:
    document: DocumentRegistryEntry
    created: bool


class DocumentRepository(Protocol):
    async def create(self, document: DocumentRegistryEntry) -> DocumentCreateResult: ...

    async def get(self, tenant_id: UUID, document_id: UUID) -> DocumentRegistryEntry: ...

    async def list_for_patient(
        self,
        *,
        tenant_id: UUID,
        patient_id: UUID,
        facility_ids: set[UUID],
        limit: int = 100,
    ) -> list[DocumentRegistryEntry]: ...

    async def finalize_upload(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        expected_version: int,
        object_key: str,
        checksum_sha256: str,
        detected_mime: str,
    ) -> DocumentRegistryEntry: ...

    async def cancel(
        self, *, tenant_id: UUID, document_id: UUID, expected_version: int
    ) -> DocumentRegistryEntry: ...


class PostgresDocumentRepository:
    """Tenant-scoped registry repository backed by an asyncpg-compatible pool."""

    def __init__(self, pool: Any):
        self._pool = pool

    @staticmethod
    async def _set_tenant_context(connection: Any, document: DocumentRegistryEntry) -> None:
        await connection.execute(
            "SELECT set_config('app.tenant_id', $1, true)", str(document.tenant_id)
        )

    async def create(self, document: DocumentRegistryEntry) -> DocumentCreateResult:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant_context(connection, document)
                row = await connection.fetchrow(
                    _INSERT_DOCUMENT,
                    document.id,
                    document.tenant_id,
                    document.facility_id,
                    document.patient_id,
                    document.encounter_id,
                    document.uploader_actor_id,
                    document.purpose,
                    document.consent_reference,
                    document.original_filename,
                    document.declared_mime,
                    document.declared_size_bytes,
                    document.idempotency_key,
                    document.upload_expires_at,
                    document.state.value,
                    document.version,
                    document.created_at,
                    document.updated_at,
                    document.declared_document_class,
                )
                if row is not None:
                    return DocumentCreateResult(
                        document=DocumentRegistryEntry.model_validate(dict(row)),
                        created=True,
                    )

                existing_row = await connection.fetchrow(
                    _GET_BY_IDEMPOTENCY_KEY,
                    document.tenant_id,
                    document.idempotency_key,
                )
                if existing_row is None:
                    raise RuntimeError("Document idempotency conflict could not be resolved")

                existing = DocumentRegistryEntry.model_validate(dict(existing_row))
                if any(
                    getattr(existing, field) != getattr(document, field)
                    for field in _INITIATION_FIELDS
                ):
                    raise IdempotencyConflict(
                        "Idempotency key is already used by a different document registration"
                    )
                return DocumentCreateResult(document=existing, created=False)

    async def get(self, tenant_id: UUID, document_id: UUID) -> DocumentRegistryEntry:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('app.tenant_id', $1, true)", str(tenant_id)
                )
                row = await connection.fetchrow(_GET_BY_ID, tenant_id, document_id)
                if row is None:
                    raise DocumentNotFound("Document not found")
                return DocumentRegistryEntry.model_validate(dict(row))

    async def list_for_patient(
        self,
        *,
        tenant_id: UUID,
        patient_id: UUID,
        facility_ids: set[UUID],
        limit: int = 100,
    ) -> list[DocumentRegistryEntry]:
        if not facility_ids or not 1 <= limit <= 200:
            return []
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('app.tenant_id', $1, true)", str(tenant_id)
                )
                rows = await connection.fetch(
                    _LIST_FOR_PATIENT,
                    tenant_id,
                    patient_id,
                    list(facility_ids),
                    limit,
                )
        return [DocumentRegistryEntry.model_validate(dict(row)) for row in rows]

    async def finalize_upload(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        expected_version: int,
        object_key: str,
        checksum_sha256: str,
        detected_mime: str,
    ) -> DocumentRegistryEntry:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('app.tenant_id', $1, true)", str(tenant_id)
                )
                row = await connection.fetchrow(_GET_FOR_UPDATE, tenant_id, document_id)
                if row is None:
                    raise DocumentNotFound("Document not found")

                document = DocumentRegistryEntry.model_validate(dict(row))
                document.attach_upload(
                    object_key=object_key,
                    checksum_sha256=checksum_sha256,
                    detected_mime=detected_mime,
                    expected_version=expected_version,
                )
                document.transition(
                    DocumentState.QUARANTINED,
                    expected_version=document.version,
                )
                updated_row = await connection.fetchrow(
                    _FINALIZE_UPLOAD,
                    tenant_id,
                    document_id,
                    expected_version,
                    document.state.value,
                    document.object_key,
                    document.source_checksum_sha256,
                    document.detected_mime,
                    document.version,
                    document.updated_at,
                )
                if updated_row is None:
                    raise RuntimeError("Concurrent document update was not persisted")

                event_type = "DocumentUploaded.v1"
                await connection.execute(
                    _INSERT_OUTBOX_EVENT,
                    uuid4(),
                    tenant_id,
                    document_id,
                    event_type,
                    f"{document_id}:uploaded:{document.version}",
                    json.dumps(
                        [{"artifact_type": "source_document", "artifact_id": str(document_id)}]
                    ),
                    json.dumps({"state": document.state.value, "document_version": document.version}),
                )
                return DocumentRegistryEntry.model_validate(dict(updated_row))

    async def cancel(
        self, *, tenant_id: UUID, document_id: UUID, expected_version: int
    ) -> DocumentRegistryEntry:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('app.tenant_id', $1, true)", str(tenant_id)
                )
                row = await connection.fetchrow(_GET_FOR_UPDATE, tenant_id, document_id)
                if row is None:
                    raise DocumentNotFound("Document not found")
                document = DocumentRegistryEntry.model_validate(dict(row))
                document.transition(DocumentState.CANCELLED, expected_version=expected_version)
                updated_row = await connection.fetchrow(
                    _UPDATE_STATE,
                    tenant_id,
                    document_id,
                    expected_version,
                    document.state.value,
                    document.version,
                    document.updated_at,
                )
                if updated_row is None:
                    raise RuntimeError("Concurrent document cancellation was not persisted")
                return DocumentRegistryEntry.model_validate(dict(updated_row))
