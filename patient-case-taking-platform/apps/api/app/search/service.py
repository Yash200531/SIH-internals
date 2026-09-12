"""Audited clinical search, timeline, FHIR-source and CSV application service."""

import csv
import hashlib
import io
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.search.audit import (
    ClinicalSearchAuditRecord,
    ClinicalSearchAuditRepository,
)
from app.search.authorization import SearchIdentity
from app.search.contracts import (
    ClinicalSearchHit,
    ClinicalSearchQuery,
    ClinicalSearchRecord,
    ClinicalSearchResponse,
    SourceKind,
)
from app.search.timeline import LongitudinalTimeline, build_longitudinal_timeline

logger = logging.getLogger(__name__)


class SearchStore(Protocol):
    async def search(self, criteria: ClinicalSearchQuery) -> ClinicalSearchResponse: ...


class CanonicalSearchRepository(Protocol):
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


class ClinicalSearchUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class FhirRecordPage:
    records: tuple[ClinicalSearchRecord, ...]
    total: int
    has_next: bool


class ClinicalSearchService:
    def __init__(
        self,
        store: SearchStore,
        canonical: CanonicalSearchRepository,
        audit: ClinicalSearchAuditRepository,
    ) -> None:
        self._store = store
        self._canonical = canonical
        self._audit_repository = audit

    async def search(
        self,
        identity: SearchIdentity,
        criteria: ClinicalSearchQuery,
        *,
        correlation_id: UUID,
    ) -> ClinicalSearchResponse:
        started = time.monotonic()
        try:
            result = await self._store.search(criteria)
        except Exception as exc:
            logger.exception(
                "Clinical search store query failed",
                extra={"correlation_id": str(correlation_id)},
            )
            await self._audit(
                identity,
                action="search",
                criteria=criteria,
                correlation_id=correlation_id,
                started=started,
                result_count=None,
                outcome="unavailable",
            )
            raise ClinicalSearchUnavailable("Clinical search is temporarily unavailable") from exc
        await self._audit(
            identity,
            action="search",
            criteria=criteria,
            correlation_id=correlation_id,
            started=started,
            result_count=result.total,
            outcome="success",
        )
        return result

    async def timeline(
        self,
        identity: SearchIdentity,
        *,
        source_kind: SourceKind | None,
        from_date: datetime | None,
        to_date: datetime | None,
        correlation_id: UUID,
    ) -> LongitudinalTimeline:
        started = time.monotonic()
        criteria = self.criteria(
            identity,
            source_kind=source_kind,
            from_date=from_date,
            to_date=to_date,
        )
        try:
            records = await self._canonical.list_patient_records(
                tenant_id=identity.tenant_id,
                patient_id=identity.patient_id,
                facility_ids=set(identity.facility_ids),
                source_kind=source_kind,
                from_date=from_date,
                to_date=to_date,
            )
            result = build_longitudinal_timeline(identity.patient_id, records)
        except Exception as exc:
            logger.exception(
                "Canonical clinical timeline read failed",
                extra={"correlation_id": str(correlation_id)},
            )
            await self._audit(
                identity,
                action="timeline",
                criteria=criteria,
                correlation_id=correlation_id,
                started=started,
                result_count=None,
                outcome="error",
            )
            raise ClinicalSearchUnavailable("Timeline is temporarily unavailable") from exc
        await self._audit(
            identity,
            action="timeline",
            criteria=criteria,
            correlation_id=correlation_id,
            started=started,
            result_count=result.summary.total_events,
            outcome="success",
        )
        return result

    async def export_csv(
        self,
        identity: SearchIdentity,
        criteria: ClinicalSearchQuery,
        *,
        correlation_id: UUID,
        maximum_rows: int = 1000,
    ) -> str:
        started = time.monotonic()
        hits: list[ClinicalSearchHit] = []
        page = criteria.model_copy(update={"page_size": 50, "cursor": None})
        try:
            while len(hits) < maximum_rows:
                response = await self._store.search(page)
                hits.extend(response.hits[: maximum_rows - len(hits)])
                if response.next_cursor is None or not response.hits:
                    break
                page = page.model_copy(update={"cursor": response.next_cursor})
        except Exception as exc:
            await self._audit(
                identity,
                action="export",
                criteria=criteria,
                correlation_id=correlation_id,
                started=started,
                result_count=None,
                outcome="unavailable",
            )
            raise ClinicalSearchUnavailable("Clinical export is temporarily unavailable") from exc

        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(
            [
                "occurred_at",
                "source_kind",
                "title",
                "entity_type",
                "statement_status",
                "facility_id",
                "encounter_id",
                "source_id",
            ]
        )
        for hit in hits:
            writer.writerow(
                [
                    hit.occurred_at.isoformat(),
                    hit.source_kind.value,
                    _csv_cell(hit.title),
                    _csv_cell(hit.entity_type),
                    _csv_cell(hit.statement_status),
                    str(hit.facility_id),
                    str(hit.encounter_id),
                    str(hit.source_id),
                ]
            )
        await self._audit(
            identity,
            action="export",
            criteria=criteria,
            correlation_id=correlation_id,
            started=started,
            result_count=len(hits),
            outcome="success",
        )
        return output.getvalue()

    async def fhir_records(
        self,
        identity: SearchIdentity,
        *,
        source_kind: SourceKind,
        entity_type: str | None,
        from_date: datetime | None,
        to_date: datetime | None,
        page: int,
        page_size: int,
        correlation_id: UUID,
    ) -> FhirRecordPage:
        started = time.monotonic()
        criteria = self.criteria(
            identity,
            source_kind=source_kind,
            entity_type=entity_type,
            from_date=from_date,
            to_date=to_date,
        )
        try:
            records = await self._canonical.list_patient_records(
                tenant_id=identity.tenant_id,
                patient_id=identity.patient_id,
                facility_ids=set(identity.facility_ids),
                source_kind=source_kind,
                from_date=from_date,
                to_date=to_date,
                entity_type=entity_type,
            )
        except Exception as exc:
            await self._audit(
                identity,
                action="fhir_search",
                criteria=criteria,
                correlation_id=correlation_id,
                started=started,
                result_count=None,
                outcome="error",
            )
            raise ClinicalSearchUnavailable("FHIR search is temporarily unavailable") from exc
        start = (page - 1) * page_size
        selected = tuple(records[start : start + page_size])
        result = FhirRecordPage(selected, len(records), start + page_size < len(records))
        await self._audit(
            identity,
            action="fhir_search",
            criteria=criteria,
            correlation_id=correlation_id,
            started=started,
            result_count=len(selected),
            outcome="success",
        )
        return result

    @staticmethod
    def criteria(
        identity: SearchIdentity,
        *,
        q: str | None = None,
        source_kind: SourceKind | None = None,
        entity_type: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        page_size: int = 20,
        cursor: str | None = None,
    ) -> ClinicalSearchQuery:
        return ClinicalSearchQuery(
            tenant_id=identity.tenant_id,
            patient_id=identity.patient_id,
            facility_ids=tuple(sorted(identity.facility_ids, key=str)),
            q=q,
            source_kind=source_kind,
            entity_type=entity_type,
            from_date=from_date,
            to_date=to_date,
            page_size=page_size,
            cursor=cursor,
        )

    async def _audit(
        self,
        identity: SearchIdentity,
        *,
        action: str,
        criteria: ClinicalSearchQuery,
        correlation_id: UUID,
        started: float,
        result_count: int | None,
        outcome: str,
    ) -> None:
        query_hash = hashlib.sha256((criteria.q or "").encode("utf-8")).hexdigest()
        try:
            await self._audit_repository.record(
                ClinicalSearchAuditRecord(
                    tenant_id=identity.tenant_id,
                    patient_id=identity.patient_id,
                    actor_id=identity.actor_id,
                    actor_role=identity.actor_role,
                    action=action,
                    authorized_facility_ids=tuple(
                        sorted(identity.facility_ids, key=str)
                    ),
                    query_sha256=query_hash,
                    filter_metadata={
                        "source_kind": criteria.source_kind.value
                        if criteria.source_kind
                        else None,
                        "entity_type": criteria.entity_type,
                        "from": criteria.from_date.isoformat()
                        if criteria.from_date
                        else None,
                        "to": criteria.to_date.isoformat() if criteria.to_date else None,
                        "page_size": criteria.page_size,
                        "cursor_present": criteria.cursor is not None,
                    },
                    result_count=result_count,
                    latency_ms=max(0, int((time.monotonic() - started) * 1000)),
                    outcome=outcome,
                    correlation_id=correlation_id,
                )
            )
        except Exception as exc:
            # Clinical data is not returned when the required durable access
            # record cannot be written, and storage details stay server-side.
            raise ClinicalSearchUnavailable(
                "Clinical retrieval is temporarily unavailable"
            ) from exc


def _csv_cell(value: object | None) -> str:
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text
