"""Canonical PostgreSQL readers for the rebuildable search projection."""

import json
from datetime import datetime
from typing import Any, Mapping, Protocol
from uuid import UUID

from app.search.contracts import ClinicalSearchRecord, SourceKind
from app.summary_workflow.contracts import SummaryContent, SummaryStatus

_LIST_SIGNED_SUMMARIES = """
SELECT id, tenant_id, facility_id, patient_id, encounter_id, status, content,
       signed_at
FROM clinical_summary_workflow
WHERE tenant_id = $1 AND patient_id = $2
  AND facility_id = ANY($3::UUID[]) AND status = 'signed'
  AND ($4::TIMESTAMPTZ IS NULL OR signed_at >= $4)
  AND ($5::TIMESTAMPTZ IS NULL OR signed_at <= $5)
ORDER BY signed_at DESC, id
"""

_LIST_REVIEWED_FACTS = """
SELECT id, tenant_id, facility_id, patient_id, encounter_id, document_id,
       entity_type, normalized_value, unit, document_statement,
       clinician_confirmed_current, active, promoted_at
FROM reviewed_document_fact
WHERE tenant_id = $1 AND patient_id = $2
  AND facility_id = ANY($3::UUID[]) AND active
  AND ($4::TIMESTAMPTZ IS NULL OR promoted_at >= $4)
  AND ($5::TIMESTAMPTZ IS NULL OR promoted_at <= $5)
  AND ($6::VARCHAR IS NULL OR entity_type = $6)
ORDER BY promoted_at DESC, id
"""

_GET_SIGNED_SUMMARY = """
SELECT id, tenant_id, facility_id, patient_id, encounter_id, status, content,
       signed_at
FROM clinical_summary_workflow
WHERE tenant_id = $1 AND id = $2 AND status = 'signed'
"""

_LIST_DOCUMENT_FACTS = """
SELECT id, tenant_id, facility_id, patient_id, encounter_id, document_id,
       entity_type, normalized_value, unit, document_statement,
       clinician_confirmed_current, active, promoted_at
FROM reviewed_document_fact
WHERE tenant_id = $1 AND document_id = $2 AND active
ORDER BY promoted_at, id
"""

_LIST_TENANT_SIGNED_SUMMARIES = """
SELECT id, tenant_id, facility_id, patient_id, encounter_id, status, content,
       signed_at
FROM clinical_summary_workflow
WHERE tenant_id = $1 AND status = 'signed'
ORDER BY signed_at DESC, id
"""

_LIST_TENANT_REVIEWED_FACTS = """
SELECT id, tenant_id, facility_id, patient_id, encounter_id, document_id,
       entity_type, normalized_value, unit, document_statement,
       clinician_confirmed_current, active, promoted_at
FROM reviewed_document_fact
WHERE tenant_id = $1 AND active
ORDER BY promoted_at DESC, id
"""


class InvalidCanonicalSearchSource(ValueError):
    pass


class ClinicalProjectionRepository(Protocol):
    async def list_patient_records(
        self,
        *,
        tenant_id: UUID,
        patient_id: UUID,
        facility_ids: set[UUID],
        source_kind: SourceKind | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        entity_type: str | None = None,
    ) -> list[ClinicalSearchRecord]: ...

    async def get_signed_summary_record(
        self, *, tenant_id: UUID, summary_id: UUID
    ) -> ClinicalSearchRecord | None: ...

    async def list_document_fact_records(
        self, *, tenant_id: UUID, document_id: UUID
    ) -> list[ClinicalSearchRecord]: ...

    async def list_tenant_records(
        self, *, tenant_id: UUID
    ) -> list[ClinicalSearchRecord]: ...


def signed_summary_to_record(row: Mapping[str, Any]) -> ClinicalSearchRecord:
    status = row.get("status")
    status_value = status.value if isinstance(status, SummaryStatus) else status
    if status_value != SummaryStatus.SIGNED.value or row.get("signed_at") is None:
        raise InvalidCanonicalSearchSource("only signed summaries may be indexed")
    content_value = row.get("content")
    if isinstance(content_value, str):
        try:
            content_value = json.loads(content_value)
        except json.JSONDecodeError as exc:
            raise InvalidCanonicalSearchSource("summary content is invalid JSON") from exc
    try:
        content = SummaryContent.model_validate(content_value)
    except (TypeError, ValueError) as exc:
        raise InvalidCanonicalSearchSource("summary content is invalid") from exc
    parts = [
        content.chief_complaint,
        *content.history_of_present_illness,
        *content.relevant_negatives,
        *content.document_facts,
        *content.red_flags,
        *content.uncertainties,
    ]
    return ClinicalSearchRecord(
        record_id=f"summary:{row['id']}",
        tenant_id=row["tenant_id"],
        facility_id=row["facility_id"],
        patient_id=row["patient_id"],
        encounter_id=row["encounter_id"],
        source_kind=SourceKind.SIGNED_SUMMARY,
        source_id=row["id"],
        title=content.chief_complaint,
        content=" · ".join(part for part in parts if part)[:50_000],
        occurred_at=row["signed_at"],
        security_labels=["human-reviewed", "restricted", "clinician-signed"],
    )


def reviewed_fact_to_record(row: Mapping[str, Any]) -> ClinicalSearchRecord:
    if row.get("active") is not True:
        raise InvalidCanonicalSearchSource("only active reviewed facts may be indexed")
    value = str(row.get("normalized_value") or "").strip()
    entity_type = str(row.get("entity_type") or "").strip()
    if not value or not entity_type:
        raise InvalidCanonicalSearchSource("reviewed fact is missing searchable content")
    unit = str(row["unit"]).strip() if row.get("unit") else None
    content = f"{value} {unit}" if unit else value
    statement_status = (
        "clinician_confirmed_current"
        if row.get("clinician_confirmed_current") is True
        else "document_stated"
    )
    return ClinicalSearchRecord(
        record_id=f"fact:{row['id']}",
        tenant_id=row["tenant_id"],
        facility_id=row["facility_id"],
        patient_id=row["patient_id"],
        encounter_id=row["encounter_id"],
        document_id=row["document_id"],
        source_kind=SourceKind.REVIEWED_FACT,
        source_id=row["id"],
        title=entity_type.replace("_", " ").title(),
        content=content,
        entity_type=entity_type,
        statement_status=statement_status,
        occurred_at=row["promoted_at"],
        security_labels=["human-reviewed", "restricted"],
    )


class PostgresClinicalProjectionRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def list_patient_records(
        self,
        *,
        tenant_id: UUID,
        patient_id: UUID,
        facility_ids: set[UUID],
        source_kind: SourceKind | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        entity_type: str | None = None,
    ) -> list[ClinicalSearchRecord]:
        if not facility_ids:
            return []
        summary_rows: list[Any] = []
        fact_rows: list[Any] = []
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                if source_kind in (None, SourceKind.SIGNED_SUMMARY):
                    summary_rows = await connection.fetch(
                        _LIST_SIGNED_SUMMARIES,
                        tenant_id,
                        patient_id,
                        list(facility_ids),
                        from_date,
                        to_date,
                    )
                if source_kind in (None, SourceKind.REVIEWED_FACT):
                    fact_rows = await connection.fetch(
                        _LIST_REVIEWED_FACTS,
                        tenant_id,
                        patient_id,
                        list(facility_ids),
                        from_date,
                        to_date,
                        entity_type,
                    )
        records = [signed_summary_to_record(row) for row in summary_rows]
        records.extend(reviewed_fact_to_record(row) for row in fact_rows)
        records.sort(key=lambda item: item.record_id)
        records.sort(key=lambda item: item.occurred_at, reverse=True)
        return records

    async def get_signed_summary_record(
        self, *, tenant_id: UUID, summary_id: UUID
    ) -> ClinicalSearchRecord | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                row = await connection.fetchrow(_GET_SIGNED_SUMMARY, tenant_id, summary_id)
        return signed_summary_to_record(row) if row is not None else None

    async def list_document_fact_records(
        self, *, tenant_id: UUID, document_id: UUID
    ) -> list[ClinicalSearchRecord]:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                rows = await connection.fetch(_LIST_DOCUMENT_FACTS, tenant_id, document_id)
        return [reviewed_fact_to_record(row) for row in rows]

    async def list_tenant_records(
        self, *, tenant_id: UUID
    ) -> list[ClinicalSearchRecord]:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._set_tenant(connection, tenant_id)
                summary_rows = await connection.fetch(
                    _LIST_TENANT_SIGNED_SUMMARIES, tenant_id
                )
                fact_rows = await connection.fetch(_LIST_TENANT_REVIEWED_FACTS, tenant_id)
        records = [signed_summary_to_record(row) for row in summary_rows]
        records.extend(reviewed_fact_to_record(row) for row in fact_rows)
        records.sort(key=lambda item: item.record_id)
        records.sort(key=lambda item: item.occurred_at, reverse=True)
        return records

    @staticmethod
    async def _set_tenant(connection: Any, tenant_id: UUID) -> None:
        await connection.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_id))
