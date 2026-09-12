from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.search.audit import InMemoryClinicalSearchAuditRepository
from app.search.authorization import SearchIdentity
from app.search.contracts import (
    ClinicalSearchHit,
    ClinicalSearchQuery,
    ClinicalSearchRecord,
    ClinicalSearchResponse,
    SearchFacets,
    SourceKind,
)
from app.search.service import ClinicalSearchService, ClinicalSearchUnavailable


def _identity() -> SearchIdentity:
    return SearchIdentity(
        tenant_id=uuid4(),
        patient_id=uuid4(),
        actor_id=uuid4(),
        actor_role="doctor",
        facility_ids=frozenset({uuid4()}),
    )


def _record(identity: SearchIdentity, **updates) -> ClinicalSearchRecord:
    source_id = uuid4()
    values = {
        "record_id": f"summary:{source_id}",
        "tenant_id": identity.tenant_id,
        "facility_id": next(iter(identity.facility_ids)),
        "patient_id": identity.patient_id,
        "encounter_id": uuid4(),
        "source_kind": SourceKind.SIGNED_SUMMARY,
        "source_id": source_id,
        "title": "=unsafe title",
        "content": "Reviewed myocardial infarction",
        "occurred_at": datetime.now(UTC),
        "security_labels": ["human-reviewed", "clinician-signed"],
    }
    values.update(updates)
    return ClinicalSearchRecord(**values)


class _Store:
    def __init__(self, identity: SearchIdentity) -> None:
        self.identity = identity
        self.calls: list[ClinicalSearchQuery] = []
        self.fail = False

    async def search(self, criteria: ClinicalSearchQuery) -> ClinicalSearchResponse:
        self.calls.append(criteria)
        if self.fail:
            raise RuntimeError("elasticsearch down")
        record = _record(self.identity)
        return ClinicalSearchResponse(
            total=1,
            hits=[
                ClinicalSearchHit(
                    **record.model_dump(exclude={"tenant_id", "content", "security_labels"})
                )
            ],
            facets=SearchFacets(source_kinds={"signed_summary": 1}),
            took_ms=2,
        )


class _Canonical:
    def __init__(self, records: list[ClinicalSearchRecord]) -> None:
        self.records = records
        self.calls = []

    async def list_patient_records(self, **kwargs):
        self.calls.append(kwargs)
        return [
            record
            for record in self.records
            if record.patient_id == kwargs["patient_id"]
            and record.facility_id in kwargs["facility_ids"]
            and (kwargs.get("source_kind") is None or record.source_kind == kwargs["source_kind"])
            and (kwargs.get("entity_type") is None or record.entity_type == kwargs["entity_type"])
        ]


class _UnavailableAudit:
    async def record(self, _entry) -> None:
        raise RuntimeError("audit database connection details")


@pytest.mark.asyncio
async def test_search_audit_hashes_query_without_storing_narrative() -> None:
    identity = _identity()
    audit = InMemoryClinicalSearchAuditRepository()
    service = ClinicalSearchService(_Store(identity), _Canonical([]), audit)
    criteria = service.criteria(identity, q="private chest pain")

    result = await service.search(identity, criteria, correlation_id=uuid4())

    assert result.total == 1
    entry = audit.entries[0]
    assert len(entry.query_sha256) == 64
    assert "private chest pain" not in str(entry.model_dump())
    assert entry.action == "search"
    assert entry.outcome == "success"


@pytest.mark.asyncio
async def test_search_failure_is_audited_and_returns_safe_unavailable_error() -> None:
    identity = _identity()
    audit = InMemoryClinicalSearchAuditRepository()
    store = _Store(identity)
    store.fail = True
    service = ClinicalSearchService(store, _Canonical([]), audit)

    with pytest.raises(ClinicalSearchUnavailable, match="temporarily unavailable"):
        await service.search(
            identity,
            service.criteria(identity, q="secret"),
            correlation_id=uuid4(),
        )
    assert audit.entries[0].outcome == "unavailable"
    assert audit.entries[0].result_count is None


@pytest.mark.asyncio
async def test_timeline_and_fhir_use_canonical_reviewed_records() -> None:
    identity = _identity()
    summary = _record(identity)
    fact = _record(
        identity,
        record_id=f"fact:{uuid4()}",
        source_kind=SourceKind.REVIEWED_FACT,
        document_id=uuid4(),
        entity_type="medication_statement",
        statement_status="document_stated",
        security_labels=["human-reviewed", "restricted"],
    )
    canonical = _Canonical([summary, fact])
    audit = InMemoryClinicalSearchAuditRepository()
    service = ClinicalSearchService(_Store(identity), canonical, audit)

    timeline = await service.timeline(
        identity,
        source_kind=None,
        from_date=None,
        to_date=None,
        correlation_id=uuid4(),
    )
    page = await service.fhir_records(
        identity,
        source_kind=SourceKind.REVIEWED_FACT,
        entity_type="medication_statement",
        from_date=None,
        to_date=None,
        page=1,
        page_size=1,
        correlation_id=uuid4(),
    )

    assert timeline.summary.total_events == 2
    assert timeline.summary.signed_summary_count == 1
    assert page.records == (fact,)
    assert [entry.action for entry in audit.entries] == ["timeline", "fhir_search"]


@pytest.mark.asyncio
async def test_csv_export_neutralizes_spreadsheet_formulas() -> None:
    identity = _identity()
    audit = InMemoryClinicalSearchAuditRepository()
    service = ClinicalSearchService(_Store(identity), _Canonical([]), audit)

    content = await service.export_csv(
        identity,
        service.criteria(identity, q="reviewed"),
        correlation_id=uuid4(),
    )

    assert "'=unsafe title" in content
    assert audit.entries[0].action == "export"
    assert audit.entries[0].result_count == 1


@pytest.mark.asyncio
async def test_successful_result_fails_closed_when_durable_audit_is_unavailable() -> None:
    identity = _identity()
    service = ClinicalSearchService(_Store(identity), _Canonical([]), _UnavailableAudit())

    with pytest.raises(ClinicalSearchUnavailable, match="temporarily unavailable") as error:
        await service.search(
            identity,
            service.criteria(identity, q="private"),
            correlation_id=uuid4(),
        )

    assert "connection details" not in str(error.value)
