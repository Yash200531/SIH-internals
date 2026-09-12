"""Reviewed-fact promotion and rebuildable clinical projections."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.documents.repository import DocumentNotFound
from app.documents.review import ReviewConflict

_GET_DOCUMENT_FOR_UPDATE = """
SELECT * FROM document_registry
WHERE tenant_id = $1 AND id = $2
FOR UPDATE
"""

_GET_RECEIPT = """
SELECT promoted_fact_count
FROM document_promotion_receipt
WHERE tenant_id = $1 AND event_id = $2
"""

_PROMOTABLE_CANDIDATES = """
SELECT candidate.candidate_id, candidate.version AS candidate_version,
       candidate.entity_type, candidate.normalized_value, candidate.unit,
       candidate.source_page_artifact_id, candidate.source_ocr_artifact_id,
       candidate.source_region_id, candidate.source_page_number,
       candidate.document_statement, candidate.clinician_confirmed_current,
       decision.id AS review_decision_id
FROM document_extraction_candidate AS candidate
JOIN LATERAL (
    SELECT review.id
    FROM document_review_decision AS review
    WHERE review.tenant_id = candidate.tenant_id
      AND review.document_id = candidate.document_id
      AND review.candidate_id = candidate.candidate_id
      AND review.resulting_candidate_version = candidate.version
    ORDER BY review.created_at DESC
    LIMIT 1
) AS decision ON TRUE
WHERE candidate.tenant_id = $1 AND candidate.document_id = $2
  AND candidate.review_state IN ('accepted', 'corrected')
  AND candidate.normalized_value IS NOT NULL
ORDER BY candidate.candidate_id
"""

_INSERT_FACT = """
INSERT INTO reviewed_document_fact (
    id, tenant_id, facility_id, patient_id, encounter_id, document_id,
    candidate_id, candidate_version, review_decision_id, entity_type,
    normalized_value, unit, source_page_artifact_id, source_ocr_artifact_id,
    source_region_id, source_page_number, document_statement,
    clinician_confirmed_current
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
    $15, $16, $17, $18
)
ON CONFLICT (tenant_id, candidate_id, candidate_version) DO NOTHING
RETURNING id
"""

_INSERT_STATUS = """
INSERT INTO document_fact_status_history (
    id, tenant_id, document_id, fact_id, actor_id, actor_role, action, reason_code
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT (tenant_id, id) DO NOTHING
"""

_INSERT_RECEIPT = """
INSERT INTO document_promotion_receipt (
    event_id, tenant_id, document_id, promoted_fact_count
) VALUES ($1, $2, $3, $4)
"""

_GET_FACTS = """
SELECT id, patient_id, encounter_id, document_id, candidate_id, entity_type,
       normalized_value, unit, source_page_artifact_id, source_ocr_artifact_id,
       source_region_id, source_page_number, document_statement,
       clinician_confirmed_current, promoted_at
FROM reviewed_document_fact
WHERE tenant_id = $1 AND document_id = $2 AND active
ORDER BY promoted_at, id
"""

_DELETE_TIMELINE = "DELETE FROM clinical_timeline_projection WHERE tenant_id = $1 AND document_id = $2"
_DELETE_FHIR = "DELETE FROM document_fhir_projection WHERE tenant_id = $1 AND document_id = $2"
_DELETE_SEARCH = "DELETE FROM document_search_projection WHERE tenant_id = $1 AND document_id = $2"

_INSERT_TIMELINE = """
INSERT INTO clinical_timeline_projection (
    id, tenant_id, patient_id, encounter_id, document_id, fact_id,
    event_type, display_value, unit, statement_status, occurred_at
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
"""

_INSERT_FHIR = """
INSERT INTO document_fhir_projection (
    id, tenant_id, document_id, fact_id, resource_type, resource
) VALUES ($1, $2, $3, $4, 'Basic', $5)
"""

_INSERT_SEARCH = """
INSERT INTO document_search_projection (
    id, tenant_id, patient_id, document_id, fact_id, entity_type,
    normalized_text, statement_status
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
"""

_GET_ACTIVE_FACTS_FOR_UPDATE = """
SELECT id FROM reviewed_document_fact
WHERE tenant_id = $1 AND document_id = $2 AND active
FOR UPDATE
"""

_LIST_FACTS = """
SELECT id, patient_id, encounter_id, document_id, candidate_id, entity_type,
       normalized_value, unit, source_page_artifact_id, source_ocr_artifact_id,
       source_region_id, source_page_number, document_statement,
       clinician_confirmed_current, active, promoted_at, withdrawn_at,
       withdrawal_reason_code
FROM reviewed_document_fact
WHERE tenant_id = $1 AND document_id = $2
ORDER BY promoted_at, id
"""

_LIST_TIMELINE = """
SELECT timeline.id, timeline.patient_id, timeline.encounter_id,
       timeline.document_id, timeline.fact_id, timeline.event_type,
       timeline.display_value, timeline.unit, timeline.statement_status,
       timeline.occurred_at
FROM clinical_timeline_projection AS timeline
JOIN document_registry AS document
  ON document.tenant_id = timeline.tenant_id
 AND document.id = timeline.document_id
WHERE timeline.tenant_id = $1 AND timeline.patient_id = $2
  AND document.facility_id = ANY($3::UUID[])
ORDER BY timeline.occurred_at DESC, timeline.id
LIMIT $4
"""

_COUNT_TIMELINE = """
SELECT COUNT(*)
FROM clinical_timeline_projection AS timeline
JOIN document_registry AS document
  ON document.tenant_id = timeline.tenant_id
 AND document.id = timeline.document_id
WHERE timeline.tenant_id = $1 AND timeline.patient_id = $2
  AND document.facility_id = ANY($3::UUID[])
"""

_LIST_FHIR = """
SELECT fhir.resource
FROM document_fhir_projection AS fhir
WHERE fhir.tenant_id = $1 AND fhir.document_id = $2
ORDER BY fhir.id
"""

_WITHDRAW_FACTS = """
UPDATE reviewed_document_fact
SET active = FALSE, withdrawn_at = CURRENT_TIMESTAMP, withdrawal_reason_code = $3
WHERE tenant_id = $1 AND document_id = $2 AND active
"""

_INSERT_EVENT = """
INSERT INTO document_outbox (
    event_id, tenant_id, aggregate_id, event_type, event_version, producer,
    correlation_id, data_classification, idempotency_key, artifact_refs, payload
) VALUES ($1, $2, $3, $4, 1, 'document-promotion-worker', $5, 'restricted', $6, $7, $8)
ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
"""


@dataclass(frozen=True)
class PromotionResult:
    document_id: UUID
    promoted_fact_count: int
    replayed: bool


@dataclass(frozen=True)
class ReviewedDocumentFact:
    id: UUID
    patient_id: UUID
    encounter_id: UUID
    document_id: UUID
    candidate_id: UUID
    entity_type: str
    normalized_value: str
    unit: str | None
    source_page_artifact_id: UUID
    source_ocr_artifact_id: UUID | None
    source_region_id: UUID | None
    source_page_number: int
    document_statement: bool
    clinician_confirmed_current: bool
    active: bool
    promoted_at: datetime
    withdrawn_at: datetime | None
    withdrawal_reason_code: str | None


@dataclass(frozen=True)
class DocumentTimelineEntry:
    id: UUID
    patient_id: UUID
    encounter_id: UUID
    document_id: UUID
    fact_id: UUID
    event_type: str
    display_value: str
    unit: str | None
    statement_status: str
    occurred_at: datetime


class PostgresReviewedFactRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def promote(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        source_event_id: UUID,
        actor_id: UUID,
        actor_role: str,
    ) -> PromotionResult:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                document = await self._document(connection, tenant_id, document_id)
                if document.state is not DocumentState.REVIEWED:
                    raise ReviewConflict("Only a reviewed document can be promoted")
                receipt = await connection.fetchrow(
                    _GET_RECEIPT, tenant_id, source_event_id
                )
                if receipt is not None:
                    return PromotionResult(
                        document_id,
                        receipt["promoted_fact_count"],
                        True,
                    )
                candidates = await connection.fetch(
                    _PROMOTABLE_CANDIDATES, tenant_id, document_id
                )
                fact_ids: list[UUID] = []
                for candidate in candidates:
                    fact_id = uuid5(
                        candidate["candidate_id"],
                        f"reviewed-fact:v{candidate['candidate_version']}",
                    )
                    inserted = await connection.fetchrow(
                        _INSERT_FACT,
                        fact_id,
                        tenant_id,
                        document.facility_id,
                        document.patient_id,
                        document.encounter_id,
                        document_id,
                        candidate["candidate_id"],
                        candidate["candidate_version"],
                        candidate["review_decision_id"],
                        candidate["entity_type"],
                        candidate["normalized_value"],
                        candidate["unit"],
                        candidate["source_page_artifact_id"],
                        candidate["source_ocr_artifact_id"],
                        candidate["source_region_id"],
                        candidate["source_page_number"],
                        candidate["document_statement"],
                        candidate["clinician_confirmed_current"],
                    )
                    if inserted is not None:
                        await connection.execute(
                            _INSERT_STATUS,
                            uuid5(fact_id, "status:promoted"),
                            tenant_id,
                            document_id,
                            fact_id,
                            actor_id,
                            actor_role,
                            "promoted",
                            None,
                        )
                    fact_ids.append(fact_id)
                await self._rebuild(connection, tenant_id, document_id)
                await connection.execute(
                    _INSERT_RECEIPT,
                    source_event_id,
                    tenant_id,
                    document_id,
                    len(fact_ids),
                )
                await self._event(
                    connection,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    event_type="ReviewedDocumentFactsPromoted.v1",
                    idempotency_key=f"document-promotion:{source_event_id}",
                    artifact_refs=[
                        {"artifact_type": "reviewed_document_fact", "artifact_id": str(value)}
                        for value in fact_ids
                    ],
                    payload={
                        "source_event_id": str(source_event_id),
                        "promoted_fact_count": len(fact_ids),
                    },
                )
                return PromotionResult(document_id, len(fact_ids), False)

    async def rebuild_projections(
        self, *, tenant_id: UUID, document_id: UUID
    ) -> int:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                await self._document(connection, tenant_id, document_id)
                return await self._rebuild(connection, tenant_id, document_id)

    async def list_facts(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        facility_ids: set[UUID],
    ) -> list[ReviewedDocumentFact]:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                document = await self._document(connection, tenant_id, document_id)
                if document.facility_id not in facility_ids:
                    raise PermissionError("Facility access denied")
                rows = await connection.fetch(_LIST_FACTS, tenant_id, document_id)
        return [ReviewedDocumentFact(**dict(row)) for row in rows]

    async def list_timeline(
        self,
        *,
        tenant_id: UUID,
        patient_id: UUID,
        facility_ids: set[UUID],
        limit: int = 100,
    ) -> list[DocumentTimelineEntry]:
        if not facility_ids or not 1 <= limit <= 200:
            return []
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                rows = await connection.fetch(
                    _LIST_TIMELINE, tenant_id, patient_id, list(facility_ids), limit
                )
        return [DocumentTimelineEntry(**dict(row)) for row in rows]

    async def count_timeline(
        self,
        *,
        tenant_id: UUID,
        patient_id: UUID,
        facility_ids: set[UUID],
    ) -> int:
        if not facility_ids:
            return 0
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                count = await connection.fetchval(
                    _COUNT_TIMELINE, tenant_id, patient_id, list(facility_ids)
                )
        return int(count or 0)

    async def list_fhir_resources(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        facility_ids: set[UUID],
    ) -> list[dict[str, object]]:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                document = await self._document(connection, tenant_id, document_id)
                if document.facility_id not in facility_ids:
                    raise PermissionError("Facility access denied")
                rows = await connection.fetch(_LIST_FHIR, tenant_id, document_id)
        resources: list[dict[str, object]] = []
        for row in rows:
            resource = row["resource"]
            resources.append(
                json.loads(resource) if isinstance(resource, str) else dict(resource)
            )
        return resources

    async def withdraw(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        actor_id: UUID,
        actor_role: str,
        reason_code: str,
        facility_ids: set[UUID],
    ) -> int:
        if actor_role != "doctor":
            raise PermissionError("Doctor role required to withdraw reviewed facts")
        if not reason_code or len(reason_code) > 64:
            raise ValueError("Withdrawal reason code is invalid")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                document = await self._document(connection, tenant_id, document_id)
                if document.facility_id not in facility_ids:
                    raise PermissionError("Facility access denied")
                facts = await connection.fetch(
                    _GET_ACTIVE_FACTS_FOR_UPDATE, tenant_id, document_id
                )
                await connection.execute(
                    _WITHDRAW_FACTS, tenant_id, document_id, reason_code
                )
                for fact in facts:
                    await connection.execute(
                        _INSERT_STATUS,
                        uuid5(fact["id"], f"status:withdrawn:{reason_code}"),
                        tenant_id,
                        document_id,
                        fact["id"],
                        actor_id,
                        actor_role,
                        "withdrawn",
                        reason_code,
                    )
                await self._rebuild(connection, tenant_id, document_id)
                await self._event(
                    connection,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    event_type="ReviewedDocumentFactsWithdrawn.v1",
                    idempotency_key=f"document-withdrawal:{document_id}:{reason_code}",
                    artifact_refs=[],
                    payload={
                        "withdrawn_fact_count": len(facts),
                        "reason_code": reason_code,
                    },
                )
                return len(facts)

    async def _rebuild(
        self, connection: Any, tenant_id: UUID, document_id: UUID
    ) -> int:
        facts = await connection.fetch(_GET_FACTS, tenant_id, document_id)
        await connection.execute(_DELETE_TIMELINE, tenant_id, document_id)
        await connection.execute(_DELETE_FHIR, tenant_id, document_id)
        await connection.execute(_DELETE_SEARCH, tenant_id, document_id)
        for fact in facts:
            statement_status = (
                "clinician_confirmed_current"
                if fact["clinician_confirmed_current"]
                else "document_stated"
            )
            timeline_id = uuid5(fact["id"], "timeline-projection.v1")
            fhir_id = uuid5(fact["id"], "fhir-projection.v1")
            search_id = uuid5(fact["id"], "search-projection.v1")
            await connection.execute(
                _INSERT_TIMELINE,
                timeline_id,
                tenant_id,
                fact["patient_id"],
                fact["encounter_id"],
                document_id,
                fact["id"],
                fact["entity_type"],
                fact["normalized_value"],
                fact["unit"],
                statement_status,
                fact["promoted_at"],
            )
            resource = {
                "resourceType": "Basic",
                "id": str(fhir_id),
                "meta": {"tag": [{"code": statement_status}]},
                "subject": {"reference": f"Patient/{fact['patient_id']}"},
                "extension": [
                    {
                        "url": "https://medikiosk.example/fhir/StructureDefinition/document-fact-type",
                        "valueCode": fact["entity_type"],
                    },
                    {
                        "url": "https://medikiosk.example/fhir/StructureDefinition/document-fact-value",
                        "valueString": fact["normalized_value"],
                    },
                    {
                        "url": "https://medikiosk.example/fhir/StructureDefinition/clinician-confirmed-current",
                        "valueBoolean": fact["clinician_confirmed_current"],
                    },
                ],
            }
            await connection.execute(
                _INSERT_FHIR,
                fhir_id,
                tenant_id,
                document_id,
                fact["id"],
                json.dumps(resource),
            )
            await connection.execute(
                _INSERT_SEARCH,
                search_id,
                tenant_id,
                fact["patient_id"],
                document_id,
                fact["id"],
                fact["entity_type"],
                fact["normalized_value"],
                statement_status,
            )
        return len(facts)

    @staticmethod
    async def _document(
        connection: Any, tenant_id: UUID, document_id: UUID
    ) -> DocumentRegistryEntry:
        row = await connection.fetchrow(
            _GET_DOCUMENT_FOR_UPDATE, tenant_id, document_id
        )
        if row is None:
            raise DocumentNotFound("Document not found")
        return DocumentRegistryEntry.model_validate(dict(row))

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
        artifact_refs: list[dict[str, str]],
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
            json.dumps(artifact_refs),
            json.dumps(payload),
        )
