from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.search.contracts import SourceKind
from app.search.projection import (
    InvalidCanonicalSearchSource,
    PostgresClinicalProjectionRepository,
    reviewed_fact_to_record,
    signed_summary_to_record,
)


def _summary_row(**updates):
    values = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "facility_id": uuid4(),
        "patient_id": uuid4(),
        "encounter_id": uuid4(),
        "status": "signed",
        "content": {
            "chief_complaint": "Chest discomfort",
            "history_of_present_illness": ["Started this morning"],
            "relevant_negatives": ["No fainting reported"],
            "document_facts": ["Prescription reviewed"],
            "red_flags": ["Breathing difficulty"],
            "uncertainties": ["Exact onset needs confirmation"],
            "raw_ocr": "must never be indexed",
        },
        "signed_at": datetime.now(UTC),
    }
    values.update(updates)
    return values


def _fact_row(**updates):
    values = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "facility_id": uuid4(),
        "patient_id": uuid4(),
        "encounter_id": uuid4(),
        "document_id": uuid4(),
        "entity_type": "medication_statement",
        "normalized_value": "Metformin",
        "unit": "500 mg",
        "document_statement": True,
        "clinician_confirmed_current": False,
        "active": True,
        "promoted_at": datetime.now(UTC),
        "raw_ocr": "must never be indexed",
    }
    values.update(updates)
    return values


def test_signed_summary_projection_contains_only_reviewed_structured_content() -> None:
    row = _summary_row()
    record = signed_summary_to_record(row)

    assert record.record_id == f"summary:{row['id']}"
    assert record.source_kind is SourceKind.SIGNED_SUMMARY
    assert record.title == "Chest discomfort"
    assert "Started this morning" in record.content
    assert "must never be indexed" not in record.content
    assert "clinician-signed" in record.security_labels


@pytest.mark.parametrize("status", ["draft", "in_review", "rejected", "superseded"])
def test_unsigned_summary_cannot_be_projected(status: str) -> None:
    with pytest.raises(InvalidCanonicalSearchSource, match="only signed"):
        signed_summary_to_record(_summary_row(status=status))


def test_reviewed_fact_projection_preserves_document_provenance_and_status() -> None:
    row = _fact_row()
    record = reviewed_fact_to_record(row)

    assert record.record_id == f"fact:{row['id']}"
    assert record.document_id == row["document_id"]
    assert record.content == "Metformin 500 mg"
    assert record.statement_status == "document_stated"
    assert "must never be indexed" not in record.content


def test_clinician_confirmed_fact_is_labelled_without_inferring_from_document() -> None:
    record = reviewed_fact_to_record(_fact_row(clinician_confirmed_current=True))
    assert record.statement_status == "clinician_confirmed_current"


def test_inactive_or_empty_fact_cannot_be_projected() -> None:
    with pytest.raises(InvalidCanonicalSearchSource, match="only active"):
        reviewed_fact_to_record(_fact_row(active=False))
    with pytest.raises(InvalidCanonicalSearchSource, match="missing searchable"):
        reviewed_fact_to_record(_fact_row(normalized_value=" "))


class _FetchConnection:
    def __init__(self) -> None:
        self.fetch_parameter_counts: list[int] = []

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def execute(self, *_args) -> None:
        return None

    async def fetch(self, _query, *parameters):
        self.fetch_parameter_counts.append(len(parameters))
        return []


class _FetchPool:
    def __init__(self, connection: _FetchConnection) -> None:
        self.connection = connection

    def acquire(self):
        return self.connection


@pytest.mark.asyncio
async def test_repository_uses_the_sql_parameter_count_for_each_source() -> None:
    connection = _FetchConnection()
    repository = PostgresClinicalProjectionRepository(_FetchPool(connection))

    records = await repository.list_patient_records(
        tenant_id=uuid4(),
        patient_id=uuid4(),
        facility_ids={uuid4()},
    )

    assert records == []
    assert connection.fetch_parameter_counts == [5, 6]
