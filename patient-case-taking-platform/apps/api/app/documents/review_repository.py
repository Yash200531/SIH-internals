"""Tenant-scoped, append-only repository for clinical document review."""

import hashlib
import json
from typing import Any, Protocol
from uuid import UUID, uuid4, uuid5

from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.documents.repository import DocumentNotFound
from app.documents.review import (
    FINAL_REVIEW_STATES,
    CandidateDecision,
    ManualCandidate,
    ReviewAction,
    ReviewCandidate,
    ReviewConflict,
    ReviewDocument,
    ReviewIncomplete,
    ReviewPage,
    ReviewQueueItem,
    ReviewState,
)
from app.documents.storage import PageArtifact

_QUEUE = """
SELECT document.id AS document_id, document.facility_id, document.patient_id,
       document.encounter_id,
       COALESCE(document.reviewed_document_class,
                document.suggested_document_class,
                document.declared_document_class) AS document_class,
       document.state, document.version, document.updated_at,
       COUNT(candidate.candidate_id)::INTEGER AS candidate_count,
       COUNT(candidate.candidate_id) FILTER (
           WHERE candidate.review_state NOT IN ('accepted', 'corrected', 'rejected')
       )::INTEGER AS unresolved_count
FROM document_registry AS document
LEFT JOIN document_extraction_candidate AS candidate
  ON candidate.tenant_id = document.tenant_id
 AND candidate.document_id = document.id
WHERE document.tenant_id = $1
  AND document.facility_id = ANY($2::UUID[])
  AND document.state = 'review_required'
GROUP BY document.id
ORDER BY document.updated_at ASC
LIMIT $3
"""

_GET_DOCUMENT = """
SELECT * FROM document_registry
WHERE tenant_id = $1 AND id = $2
"""

_GET_DOCUMENT_FOR_UPDATE = _GET_DOCUMENT + " FOR UPDATE"

_GET_CANDIDATES = """
SELECT candidate_id, entity_type, normalized_value, unit,
       source_page_artifact_id, source_ocr_artifact_id, source_region_id,
       source_page_number, parser_signal, negated, temporality, subject,
       uncertainty, document_statement, clinician_confirmed_current,
       review_state, version, source_page_width, source_page_height,
       source_bbox, source_polygon
FROM document_extraction_candidate
WHERE tenant_id = $1 AND document_id = $2
ORDER BY source_page_number, entity_type, candidate_id
"""

_GET_PAGE = """
SELECT id, page_number, object_key, checksum_sha256, mime, width, height,
       preprocessing_version
FROM document_page_artifact
WHERE tenant_id = $1 AND document_id = $2 AND id = $3
"""

_GET_PAGES = """
SELECT id, page_number, width, height, preprocessing_version
FROM document_page_artifact
WHERE tenant_id = $1 AND document_id = $2
ORDER BY page_number
"""

_GET_CANDIDATE_FOR_UPDATE = """
SELECT candidate_id, entity_type, normalized_value, unit,
       source_page_artifact_id, source_ocr_artifact_id, source_region_id,
       source_page_number, parser_signal, negated, temporality, subject,
       uncertainty, document_statement, clinician_confirmed_current,
       review_state, version, source_page_width, source_page_height,
       source_bbox, source_polygon
FROM document_extraction_candidate
WHERE tenant_id = $1 AND document_id = $2 AND candidate_id = $3
FOR UPDATE
"""

_GET_DECISION_BY_KEY = """
SELECT request_hash_sha256, candidate_id
FROM document_review_decision
WHERE tenant_id = $1 AND idempotency_key = $2
"""

_UPDATE_CANDIDATE = """
UPDATE document_extraction_candidate
SET review_state = $5::VARCHAR,
    normalized_value = CASE WHEN $5::VARCHAR = 'corrected' THEN $6 ELSE normalized_value END,
    unit = CASE WHEN $5::VARCHAR = 'corrected' THEN $7 ELSE unit END,
    version = version + 1
WHERE tenant_id = $1 AND document_id = $2 AND candidate_id = $3 AND version = $4
RETURNING candidate_id, entity_type, normalized_value, unit,
          source_page_artifact_id, source_ocr_artifact_id, source_region_id,
          source_page_number, parser_signal, negated, temporality, subject,
          uncertainty, document_statement, clinician_confirmed_current,
          review_state, version, source_page_width, source_page_height,
          source_bbox, source_polygon
"""

_INSERT_DECISION = """
INSERT INTO document_review_decision (
    id, tenant_id, facility_id, document_id, candidate_id, actor_id, actor_role,
    purpose, action, previous_state, resulting_state,
    expected_candidate_version, resulting_candidate_version,
    corrected_value, corrected_unit, reason_code, source_verified,
    idempotency_key, request_hash_sha256
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
    $14, $15, $16, $17, $18, $19
)
"""

_INSERT_MANUAL_CANDIDATE = """
INSERT INTO document_extraction_candidate (
    candidate_id, tenant_id, document_id, extraction_run_id, draft_id,
    entity_type, normalized_value, unit, source_page_artifact_id,
    source_ocr_artifact_id, source_region_id, source_page_number,
    parser_version, parser_signal, negated, temporality, subject, uncertainty,
    document_statement, clinician_confirmed_current, review_state, version,
    source_page_width, source_page_height, source_bbox, source_polygon,
    candidate_origin, created_by_actor_id
) VALUES (
    $1, $2, $3, NULL, NULL, $4, $5, $6, $7, NULL, NULL, $8,
    'manual.v1', 'manual_entry', FALSE, 'documented', 'patient', NULL,
    TRUE, FALSE, 'corrected', 2, $9, $10, NULL, NULL, 'manual', $11
)
RETURNING candidate_id, entity_type, normalized_value, unit,
          source_page_artifact_id, source_ocr_artifact_id, source_region_id,
          source_page_number, parser_signal, negated, temporality, subject,
          uncertainty, document_statement, clinician_confirmed_current,
          review_state, version, source_page_width, source_page_height,
          source_bbox, source_polygon
"""

_COUNT_REVIEW = """
SELECT COUNT(*)::INTEGER AS total,
       COUNT(*) FILTER (
           WHERE review_state NOT IN ('accepted', 'corrected', 'rejected')
       )::INTEGER AS unresolved
FROM document_extraction_candidate
WHERE tenant_id = $1 AND document_id = $2
"""

_GET_COMPLETION_EVENT = """
SELECT event_id
FROM document_outbox
WHERE tenant_id = $1 AND aggregate_id = $2
  AND event_type = 'DocumentReviewCompleted.v1' AND idempotency_key = $3
"""

_GET_MANUAL_REVIEW_EVENT = """
SELECT event_id
FROM document_outbox
WHERE tenant_id = $1 AND aggregate_id = $2
  AND event_type = 'DocumentManualReviewRequested.v1' AND idempotency_key = $3
"""

_UPDATE_DOCUMENT = """
UPDATE document_registry
SET state = $4, version = $5, updated_at = $6, reviewed_document_class = $7
WHERE tenant_id = $1 AND id = $2 AND version = $3
RETURNING *
"""

_INSERT_EVENT = """
INSERT INTO document_outbox (
    event_id, tenant_id, aggregate_id, event_type, event_version, producer,
    correlation_id, data_classification, idempotency_key, artifact_refs, payload
) VALUES ($1, $2, $3, $4, 1, 'document-review-api', $5, 'restricted', $6, '[]', $7)
ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
"""


class DocumentReviewRepository(Protocol):
    async def list_queue(
        self, *, tenant_id: UUID, facility_ids: set[UUID], limit: int
    ) -> list[ReviewQueueItem]: ...

    async def get(
        self, *, tenant_id: UUID, document_id: UUID
    ) -> ReviewDocument: ...

    async def get_registry(
        self, *, tenant_id: UUID, document_id: UUID
    ) -> DocumentRegistryEntry: ...

    async def get_page(
        self, *, tenant_id: UUID, document_id: UUID, page_artifact_id: UUID
    ) -> PageArtifact: ...

    async def decide(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        facility_ids: set[UUID],
        actor_id: UUID,
        actor_role: str,
        idempotency_key: str,
        candidate_id: UUID,
        decision: CandidateDecision,
    ) -> ReviewCandidate: ...

    async def add_manual_candidate(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        facility_ids: set[UUID],
        actor_id: UUID,
        actor_role: str,
        idempotency_key: str,
        candidate: ManualCandidate,
    ) -> ReviewCandidate: ...

    async def open_manual_review(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        facility_ids: set[UUID],
        actor_id: UUID,
        actor_role: str,
        expected_document_version: int,
        idempotency_key: str,
    ) -> ReviewDocument: ...

    async def finalize(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        facility_ids: set[UUID],
        actor_id: UUID,
        actor_role: str,
        expected_document_version: int,
        idempotency_key: str,
    ) -> ReviewDocument: ...


def _candidate(row: Any) -> ReviewCandidate:
    values = dict(row)
    values["review_state"] = ReviewState(values["review_state"])
    for field in (
        "source_page_width",
        "source_page_height",
        "source_bbox",
        "source_polygon",
    ):
        values.setdefault(field, None)
    # asyncpg returns JSONB as text unless a custom codec is installed.
    # Decode before tuple conversion to preserve coordinates, not characters.
    for field in ("source_bbox", "source_polygon"):
        if isinstance(values[field], str):
            values[field] = json.loads(values[field])
    if values["source_bbox"] is not None:
        values["source_bbox"] = tuple(values["source_bbox"])
    if values["source_polygon"] is not None:
        values["source_polygon"] = tuple(
            tuple(point) for point in values["source_polygon"]
        )
    return ReviewCandidate(**values)


def _request_hash(candidate_id: UUID, decision: CandidateDecision) -> str:
    payload = {
        "candidate_id": str(candidate_id),
        "action": decision.action.value,
        "expected_candidate_version": decision.expected_candidate_version,
        "corrected_value": decision.corrected_value,
        "corrected_unit": decision.corrected_unit,
        "reason_code": decision.reason_code,
        "source_verified": decision.source_verified,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class PostgresDocumentReviewRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def list_queue(
        self, *, tenant_id: UUID, facility_ids: set[UUID], limit: int = 100
    ) -> list[ReviewQueueItem]:
        if not facility_ids or not 1 <= limit <= 200:
            return []
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                rows = await connection.fetch(
                    _QUEUE, tenant_id, list(facility_ids), limit
                )
        return [ReviewQueueItem(**dict(row)) for row in rows]

    async def get(
        self, *, tenant_id: UUID, document_id: UUID
    ) -> ReviewDocument:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                row = await connection.fetchrow(_GET_DOCUMENT, tenant_id, document_id)
                if row is None:
                    raise DocumentNotFound("Document not found")
                document = DocumentRegistryEntry.model_validate(dict(row))
                candidates = await connection.fetch(
                    _GET_CANDIDATES, tenant_id, document_id
                )
                pages = await connection.fetch(_GET_PAGES, tenant_id, document_id)
        return self._detail(document, candidates, pages)

    async def get_registry(
        self, *, tenant_id: UUID, document_id: UUID
    ) -> DocumentRegistryEntry:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                row = await connection.fetchrow(_GET_DOCUMENT, tenant_id, document_id)
        if row is None:
            raise DocumentNotFound("Document not found")
        return DocumentRegistryEntry.model_validate(dict(row))

    async def get_page(
        self, *, tenant_id: UUID, document_id: UUID, page_artifact_id: UUID
    ) -> PageArtifact:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                row = await connection.fetchrow(
                    _GET_PAGE, tenant_id, document_id, page_artifact_id
                )
        if row is None:
            raise DocumentNotFound("Document page not found")
        return PageArtifact(**dict(row))

    async def decide(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        facility_ids: set[UUID],
        actor_id: UUID,
        actor_role: str,
        idempotency_key: str,
        candidate_id: UUID,
        decision: CandidateDecision,
    ) -> ReviewCandidate:
        resulting_state = decision.validate()
        if actor_role not in {"doctor", "nurse"}:
            raise PermissionError("Clinical review role required")
        if not idempotency_key or len(idempotency_key) > 128:
            raise ValueError("Review idempotency key is invalid")
        request_hash = _request_hash(candidate_id, decision)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                document = await self._authorized_document(
                    connection, tenant_id, document_id, facility_ids
                )
                replay = await connection.fetchrow(
                    _GET_DECISION_BY_KEY, tenant_id, idempotency_key
                )
                if replay is not None:
                    if (
                        replay["request_hash_sha256"] != request_hash
                        or replay["candidate_id"] != candidate_id
                    ):
                        raise ReviewConflict("Review idempotency key conflict")
                    replayed = await connection.fetchrow(
                        _GET_CANDIDATE_FOR_UPDATE,
                        tenant_id,
                        document_id,
                        candidate_id,
                    )
                    if replayed is None:
                        raise ReviewConflict("Reviewed candidate is missing")
                    return _candidate(replayed)

                row = await connection.fetchrow(
                    _GET_CANDIDATE_FOR_UPDATE,
                    tenant_id,
                    document_id,
                    candidate_id,
                )
                if row is None:
                    raise DocumentNotFound("Review candidate not found")
                current = _candidate(row)
                if current.version != decision.expected_candidate_version:
                    raise ReviewConflict("Candidate version is stale")
                updated_row = await connection.fetchrow(
                    _UPDATE_CANDIDATE,
                    tenant_id,
                    document_id,
                    candidate_id,
                    decision.expected_candidate_version,
                    resulting_state.value,
                    decision.corrected_value.strip()
                    if decision.corrected_value is not None
                    else None,
                    decision.corrected_unit,
                )
                if updated_row is None:
                    raise ReviewConflict("Concurrent candidate review")
                updated = _candidate(updated_row)
                decision_id = uuid4()
                await connection.execute(
                    _INSERT_DECISION,
                    decision_id,
                    tenant_id,
                    document.facility_id,
                    document_id,
                    candidate_id,
                    actor_id,
                    actor_role,
                    document.purpose,
                    decision.action.value,
                    current.review_state.value,
                    updated.review_state.value,
                    decision.expected_candidate_version,
                    updated.version,
                    decision.corrected_value,
                    decision.corrected_unit,
                    decision.reason_code,
                    decision.source_verified,
                    idempotency_key,
                    request_hash,
                )
                await self._event(
                    connection,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    event_type="DocumentReviewDecisionRecorded.v1",
                    idempotency_key=f"review-decision:{decision_id}",
                    payload={
                        "decision_id": str(decision_id),
                        "candidate_id": str(candidate_id),
                        "action": decision.action.value,
                        "candidate_version": updated.version,
                    },
                )
                return updated

    async def add_manual_candidate(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        facility_ids: set[UUID],
        actor_id: UUID,
        actor_role: str,
        idempotency_key: str,
        candidate: ManualCandidate,
    ) -> ReviewCandidate:
        candidate.validate()
        if actor_role not in {"doctor", "nurse"}:
            raise PermissionError("Clinical review role required")
        if not idempotency_key or len(idempotency_key) > 128:
            raise ValueError("Review idempotency key is invalid")
        candidate_id = uuid5(document_id, f"manual-candidate:{idempotency_key}")
        decision = CandidateDecision(
            action=ReviewAction.MANUAL_ENTRY,
            expected_candidate_version=1,
            corrected_value=candidate.normalized_value,
            corrected_unit=candidate.unit,
            source_verified=candidate.source_verified,
        )
        request_hash = _request_hash(candidate_id, decision)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                document = await self._authorized_document(
                    connection, tenant_id, document_id, facility_ids
                )
                replay = await connection.fetchrow(
                    _GET_DECISION_BY_KEY, tenant_id, idempotency_key
                )
                if replay is not None:
                    if (
                        replay["request_hash_sha256"] != request_hash
                        or replay["candidate_id"] != candidate_id
                    ):
                        raise ReviewConflict("Review idempotency key conflict")
                    replayed = await connection.fetchrow(
                        _GET_CANDIDATE_FOR_UPDATE,
                        tenant_id,
                        document_id,
                        replay["candidate_id"],
                    )
                    if replayed is None:
                        raise ReviewConflict("Manual review candidate is missing")
                    return _candidate(replayed)
                page = await connection.fetchrow(
                    _GET_PAGE,
                    tenant_id,
                    document_id,
                    candidate.source_page_artifact_id,
                )
                if page is None or page["page_number"] != candidate.source_page_number:
                    raise ValueError("Manual candidate source page does not match")
                inserted_row = await connection.fetchrow(
                    _INSERT_MANUAL_CANDIDATE,
                    candidate_id,
                    tenant_id,
                    document_id,
                    candidate.entity_type,
                    candidate.normalized_value.strip(),
                    candidate.unit,
                    candidate.source_page_artifact_id,
                    candidate.source_page_number,
                    page["width"],
                    page["height"],
                    actor_id,
                )
                if inserted_row is None:
                    raise ReviewConflict("Manual candidate was not persisted")
                inserted = _candidate(inserted_row)
                decision_id = uuid4()
                await connection.execute(
                    _INSERT_DECISION,
                    decision_id,
                    tenant_id,
                    document.facility_id,
                    document_id,
                    candidate_id,
                    actor_id,
                    actor_role,
                    document.purpose,
                    ReviewAction.MANUAL_ENTRY.value,
                    ReviewState.UNREVIEWED.value,
                    ReviewState.CORRECTED.value,
                    1,
                    2,
                    candidate.normalized_value.strip(),
                    candidate.unit,
                    None,
                    True,
                    idempotency_key,
                    request_hash,
                )
                await self._event(
                    connection,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    event_type="DocumentReviewDecisionRecorded.v1",
                    idempotency_key=f"review-decision:{decision_id}",
                    payload={
                        "decision_id": str(decision_id),
                        "candidate_id": str(candidate_id),
                        "action": ReviewAction.MANUAL_ENTRY.value,
                        "candidate_version": inserted.version,
                    },
                )
                return inserted

    async def open_manual_review(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        facility_ids: set[UUID],
        actor_id: UUID,
        actor_role: str,
        expected_document_version: int,
        idempotency_key: str,
    ) -> ReviewDocument:
        if actor_role not in {"doctor", "nurse"}:
            raise PermissionError("Clinical review role required")
        if not idempotency_key or len(idempotency_key) > 128:
            raise ValueError("Review idempotency key is invalid")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                row = await connection.fetchrow(
                    _GET_DOCUMENT_FOR_UPDATE, tenant_id, document_id
                )
                if row is None:
                    raise DocumentNotFound("Document not found")
                document = DocumentRegistryEntry.model_validate(dict(row))
                if document.facility_id not in facility_ids:
                    raise PermissionError("Facility access denied")
                manual_key = f"manual-review:{idempotency_key}"
                if document.state is DocumentState.REVIEW_REQUIRED:
                    replay = await connection.fetchrow(
                        _GET_MANUAL_REVIEW_EVENT,
                        tenant_id,
                        document_id,
                        manual_key,
                    )
                    if replay is None:
                        raise ReviewConflict("Document is already awaiting review")
                    candidates = await connection.fetch(
                        _GET_CANDIDATES, tenant_id, document_id
                    )
                    pages = await connection.fetch(_GET_PAGES, tenant_id, document_id)
                    return self._detail(document, candidates, pages)
                if document.state not in {
                    DocumentState.PROCESSING,
                    DocumentState.PROCESSING_FAILED,
                }:
                    raise ReviewConflict("Document cannot enter manual review")
                document._assert_version(expected_document_version)
                pages = await connection.fetch(_GET_PAGES, tenant_id, document_id)
                if not pages:
                    raise ReviewIncomplete(
                        "No normalized page is available; retry page normalization"
                    )
                document.transition(
                    DocumentState.REVIEW_REQUIRED,
                    expected_version=expected_document_version,
                )
                updated_row = await connection.fetchrow(
                    _UPDATE_DOCUMENT,
                    tenant_id,
                    document_id,
                    expected_document_version,
                    document.state.value,
                    document.version,
                    document.updated_at,
                    document.reviewed_document_class,
                )
                if updated_row is None:
                    raise ReviewConflict("Concurrent manual review request")
                await self._event(
                    connection,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    event_type="DocumentManualReviewRequested.v1",
                    idempotency_key=manual_key,
                    payload={
                        "document_version": document.version,
                        "page_count": len(pages),
                        "requested_by_actor_id": str(actor_id),
                        "requested_by_role": actor_role,
                    },
                )
                return self._detail(
                    DocumentRegistryEntry.model_validate(dict(updated_row)),
                    [],
                    pages,
                )

    async def finalize(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        facility_ids: set[UUID],
        actor_id: UUID,
        actor_role: str,
        expected_document_version: int,
        idempotency_key: str,
    ) -> ReviewDocument:
        if actor_role not in {"doctor", "nurse"}:
            raise PermissionError("Clinical review role required")
        if not idempotency_key or len(idempotency_key) > 128:
            raise ValueError("Review idempotency key is invalid")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                row = await connection.fetchrow(
                    _GET_DOCUMENT_FOR_UPDATE, tenant_id, document_id
                )
                if row is None:
                    raise DocumentNotFound("Document not found")
                document = DocumentRegistryEntry.model_validate(dict(row))
                if document.facility_id not in facility_ids:
                    raise PermissionError("Facility access denied")
                completion_key = f"review-complete:{idempotency_key}"
                if document.state is DocumentState.REVIEWED:
                    replay = await connection.fetchrow(
                        _GET_COMPLETION_EVENT,
                        tenant_id,
                        document_id,
                        completion_key,
                    )
                    if replay is None:
                        raise ReviewConflict("Document review is already complete")
                    candidates = await connection.fetch(
                        _GET_CANDIDATES, tenant_id, document_id
                    )
                    return self._detail(document, candidates)
                if document.state is not DocumentState.REVIEW_REQUIRED:
                    raise ReviewConflict("Document is not awaiting review")
                document._assert_version(expected_document_version)
                counts = await connection.fetchrow(
                    _COUNT_REVIEW, tenant_id, document_id
                )
                if counts is None or counts["total"] == 0 or counts["unresolved"]:
                    raise ReviewIncomplete("Every candidate must have a final decision")
                candidates = await connection.fetch(
                    _GET_CANDIDATES, tenant_id, document_id
                )
                if any(
                    _candidate(row).review_state not in FINAL_REVIEW_STATES
                    for row in candidates
                ):
                    raise ReviewIncomplete("Every candidate must have a final decision")
                document.transition(
                    DocumentState.REVIEWED,
                    expected_version=expected_document_version,
                )
                document.reviewed_document_class = document.declared_document_class
                updated_row = await connection.fetchrow(
                    _UPDATE_DOCUMENT,
                    tenant_id,
                    document_id,
                    expected_document_version,
                    document.state.value,
                    document.version,
                    document.updated_at,
                    document.reviewed_document_class,
                )
                if updated_row is None:
                    raise ReviewConflict("Concurrent document review")
                await self._event(
                    connection,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    event_type="DocumentReviewCompleted.v1",
                    idempotency_key=completion_key,
                    payload={
                        "document_version": document.version,
                        "reviewed_document_class": document.reviewed_document_class,
                        "reviewed_by_actor_id": str(actor_id),
                        "reviewed_by_role": actor_role,
                    },
                )
                return self._detail(
                    DocumentRegistryEntry.model_validate(dict(updated_row)),
                    candidates,
                )

    async def _authorized_document(
        self,
        connection: Any,
        tenant_id: UUID,
        document_id: UUID,
        facility_ids: set[UUID],
    ) -> DocumentRegistryEntry:
        row = await connection.fetchrow(
            _GET_DOCUMENT_FOR_UPDATE, tenant_id, document_id
        )
        if row is None:
            raise DocumentNotFound("Document not found")
        document = DocumentRegistryEntry.model_validate(dict(row))
        if document.facility_id not in facility_ids:
            raise PermissionError("Facility access denied")
        if document.state is not DocumentState.REVIEW_REQUIRED:
            raise ReviewConflict("Document is not awaiting review")
        return document

    @staticmethod
    def _detail(
        document: DocumentRegistryEntry,
        rows: Any,
        page_rows: Any = (),
    ) -> ReviewDocument:
        return ReviewDocument(
            document_id=document.id,
            tenant_id=document.tenant_id,
            facility_id=document.facility_id,
            patient_id=document.patient_id,
            encounter_id=document.encounter_id,
            purpose=document.purpose,
            document_class=(
                document.reviewed_document_class
                or document.suggested_document_class
                or document.declared_document_class
            ),
            state=document.state.value,
            version=document.version,
            updated_at=document.updated_at,
            candidates=tuple(_candidate(row) for row in rows),
            pages=tuple(ReviewPage(**dict(row)) for row in page_rows),
        )

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
        event_type: str,
        idempotency_key: str,
        payload: dict[str, object],
    ) -> None:
        await connection.execute(
            _INSERT_EVENT,
            uuid4(),
            tenant_id,
            document_id,
            event_type,
            uuid4(),
            idempotency_key,
            json.dumps(payload),
        )
