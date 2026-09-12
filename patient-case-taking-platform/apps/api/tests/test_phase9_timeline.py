from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.search.contracts import ClinicalSearchRecord, SourceKind
from app.search.timeline import MixedPatientTimeline, build_longitudinal_timeline


def _record(
    patient_id: UUID,
    *,
    source_kind: SourceKind,
    occurred_at: datetime,
    encounter_id: UUID | None = None,
    content: str = "Reviewed clinical content",
) -> ClinicalSearchRecord:
    source_id = uuid4()
    return ClinicalSearchRecord(
        record_id=f"{source_kind.value}:{source_id}",
        tenant_id=uuid4(),
        facility_id=uuid4(),
        patient_id=patient_id,
        encounter_id=encounter_id or uuid4(),
        document_id=uuid4() if source_kind is SourceKind.REVIEWED_FACT else None,
        source_kind=source_kind,
        source_id=source_id,
        title="Signed report" if source_kind is SourceKind.SIGNED_SUMMARY else "Medication",
        content=content,
        entity_type="medication_statement"
        if source_kind is SourceKind.REVIEWED_FACT
        else None,
        statement_status="document_stated"
        if source_kind is SourceKind.REVIEWED_FACT
        else None,
        occurred_at=occurred_at,
        security_labels=["human-reviewed", "restricted"],
    )


def test_timeline_aggregates_multiple_encounters_without_inference() -> None:
    patient_id = uuid4()
    now = datetime.now(UTC)
    encounter_one, encounter_two = uuid4(), uuid4()
    summary = _record(
        patient_id,
        source_kind=SourceKind.SIGNED_SUMMARY,
        occurred_at=now,
        encounter_id=encounter_one,
        content="Chest discomfort · Started today · No fainting",
    )
    fact = _record(
        patient_id,
        source_kind=SourceKind.REVIEWED_FACT,
        occurred_at=now - timedelta(days=1),
        encounter_id=encounter_two,
        content="Metformin 500 mg",
    )

    timeline = build_longitudinal_timeline(patient_id, [fact, summary])

    assert [event.record_id for event in timeline.events] == [
        summary.record_id,
        fact.record_id,
    ]
    assert timeline.events[0].details == [
        "Chest discomfort",
        "Started today",
        "No fainting",
    ]
    assert timeline.events[1].details == ["Metformin 500 mg"]
    assert timeline.events[1].statement_status == "document_stated"
    assert timeline.summary.total_events == 2
    assert timeline.summary.encounter_count == 2
    assert timeline.summary.signed_summary_count == 1
    assert timeline.summary.reviewed_fact_count == 1
    assert timeline.summary.first_event_at == fact.occurred_at
    assert timeline.summary.last_event_at == summary.occurred_at


def test_empty_timeline_has_truthful_zero_summary() -> None:
    patient_id = uuid4()
    timeline = build_longitudinal_timeline(patient_id, [])

    assert timeline.events == []
    assert timeline.summary.total_events == 0
    assert timeline.summary.encounter_count == 0
    assert timeline.summary.first_event_at is None
    assert timeline.summary.last_event_at is None


def test_timeline_rejects_mixed_patient_records() -> None:
    requested_patient = uuid4()
    record = _record(
        uuid4(),
        source_kind=SourceKind.SIGNED_SUMMARY,
        occurred_at=datetime.now(UTC),
    )
    with pytest.raises(MixedPatientTimeline):
        build_longitudinal_timeline(requested_patient, [record])


def test_timeline_order_is_stable_when_timestamps_match() -> None:
    patient_id = uuid4()
    occurred_at = datetime.now(UTC)
    records = [
        _record(patient_id, source_kind=SourceKind.REVIEWED_FACT, occurred_at=occurred_at)
        for _ in range(3)
    ]
    timeline = build_longitudinal_timeline(patient_id, list(reversed(records)))
    assert [event.record_id for event in timeline.events] == sorted(
        record.record_id for record in records
    )
