"""Deterministic longitudinal timeline assembled from reviewed search records."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.search.contracts import ClinicalSearchRecord, SourceKind


class LongitudinalTimelineEvent(BaseModel):
    record_id: str
    facility_id: UUID
    encounter_id: UUID
    document_id: UUID | None = None
    source_kind: SourceKind
    source_id: UUID
    title: str
    details: list[str] = Field(max_length=8)
    entity_type: str | None = None
    statement_status: str | None = None
    occurred_at: datetime


class LongitudinalTimelineSummary(BaseModel):
    total_events: int = Field(ge=0)
    encounter_count: int = Field(ge=0)
    signed_summary_count: int = Field(ge=0)
    reviewed_fact_count: int = Field(ge=0)
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None


class LongitudinalTimeline(BaseModel):
    patient_id: UUID
    events: list[LongitudinalTimelineEvent]
    summary: LongitudinalTimelineSummary


class MixedPatientTimeline(ValueError):
    pass


def build_longitudinal_timeline(
    patient_id: UUID, records: list[ClinicalSearchRecord]
) -> LongitudinalTimeline:
    if any(record.patient_id != patient_id for record in records):
        raise MixedPatientTimeline("timeline records must belong to one patient")
    ordered = sorted(records, key=lambda item: item.record_id)
    ordered.sort(key=lambda item: item.occurred_at, reverse=True)
    events = [
        LongitudinalTimelineEvent(
            record_id=record.record_id,
            facility_id=record.facility_id,
            encounter_id=record.encounter_id,
            document_id=record.document_id,
            source_kind=record.source_kind,
            source_id=record.source_id,
            title=record.title,
            details=_details(record),
            entity_type=record.entity_type,
            statement_status=record.statement_status,
            occurred_at=record.occurred_at,
        )
        for record in ordered
    ]
    event_times = [event.occurred_at for event in events]
    return LongitudinalTimeline(
        patient_id=patient_id,
        events=events,
        summary=LongitudinalTimelineSummary(
            total_events=len(events),
            encounter_count=len({event.encounter_id for event in events}),
            signed_summary_count=sum(
                event.source_kind is SourceKind.SIGNED_SUMMARY for event in events
            ),
            reviewed_fact_count=sum(
                event.source_kind is SourceKind.REVIEWED_FACT for event in events
            ),
            first_event_at=min(event_times) if event_times else None,
            last_event_at=max(event_times) if event_times else None,
        ),
    )


def _details(record: ClinicalSearchRecord) -> list[str]:
    if record.source_kind is SourceKind.REVIEWED_FACT:
        return [record.content]
    return [part.strip() for part in record.content.split(" · ") if part.strip()][:8]
