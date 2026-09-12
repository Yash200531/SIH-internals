import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.search.contracts import ClinicalSearchQuery, ClinicalSearchRecord, SourceKind
from app.search.query import (
    InvalidSearchCursor,
    InvalidSynonymConfiguration,
    build_search_request,
    decode_cursor,
    encode_cursor,
    load_synonym_rules,
)


def _query(**updates) -> ClinicalSearchQuery:
    values = {
        "tenant_id": uuid4(),
        "patient_id": uuid4(),
        "facility_ids": (uuid4(), uuid4()),
    }
    values.update(updates)
    return ClinicalSearchQuery(**values)


def test_search_record_requires_human_review_and_normalizes_text() -> None:
    record = ClinicalSearchRecord(
        record_id=f"summary:{uuid4()}",
        tenant_id=uuid4(),
        facility_id=uuid4(),
        patient_id=uuid4(),
        encounter_id=uuid4(),
        source_kind=SourceKind.SIGNED_SUMMARY,
        source_id=uuid4(),
        title="  Chest   discomfort ",
        content="  Started   this morning ",
        occurred_at=datetime.now(UTC),
        security_labels=["RESTRICTED", "human-reviewed", "human-reviewed"],
    )

    assert record.title == "Chest discomfort"
    assert record.content == "Started this morning"
    assert record.security_labels == ["human-reviewed", "restricted"]

    with pytest.raises(ValidationError, match="human reviewed"):
        record.model_copy(update={"security_labels": ["restricted"]}).model_dump()
        ClinicalSearchRecord(**{**record.model_dump(), "security_labels": ["restricted"]})


def test_query_rejects_reverse_date_window_and_bounds_page_size() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="from_date"):
        _query(from_date=now, to_date=now - timedelta(days=1))
    with pytest.raises(ValidationError):
        _query(page_size=51)


def test_query_normalizes_facilities_and_optional_text() -> None:
    facility_id = uuid4()
    query = _query(
        facility_ids=(facility_id, facility_id),
        q="  chest    pain ",
        entity_type="  medication_statement ",
    )
    assert query.facility_ids == (facility_id,)
    assert query.q == "chest pain"
    assert query.entity_type == "medication_statement"


def test_query_builder_always_filters_tenant_patient_facility_and_review_state() -> None:
    criteria = _query(q="chest pain", source_kind=SourceKind.SIGNED_SUMMARY)
    request = build_search_request(criteria)
    filters = request["query"]["bool"]["filter"]

    assert {"term": {"tenant_id": str(criteria.tenant_id)}} in filters
    assert {"term": {"patient_id": str(criteria.patient_id)}} in filters
    assert {"terms": {"facility_id": [str(value) for value in criteria.facility_ids]}} in filters
    assert {"term": {"security_labels": "human-reviewed"}} in filters
    assert {"term": {"source_kind": "signed_summary"}} in filters
    assert "query_string" not in json.dumps(request)
    assert request["highlight"]["fragment_size"] == 160
    assert request["highlight"]["number_of_fragments"] == 2


def test_filter_only_search_uses_deterministic_date_sort_without_highlights() -> None:
    request = build_search_request(_query())
    assert request["query"]["bool"]["must"] == []
    assert request["sort"] == [{"occurred_at": "desc"}, {"record_id": "asc"}]
    assert "highlight" not in request


def test_cursor_round_trip_and_rejection() -> None:
    values = [0.75, "2026-09-05T10:30:00+00:00", "summary:abc"]
    cursor = encode_cursor(values)
    assert decode_cursor(cursor) == values
    assert build_search_request(_query(q="pain", cursor=cursor))["search_after"] == values

    for invalid in ("%%%", encode_cursor(["x"]).replace("1", "2") + "garbage"):
        with pytest.raises(InvalidSearchCursor):
            decode_cursor(invalid)


def test_synonym_file_is_versioned_and_loads_safe_unicode_rules() -> None:
    api_root = Path(__file__).resolve().parents[1]
    path = api_root / "app" / "search" / "medical_synonyms.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    rules = load_synonym_rules(path)

    assert payload["status"] == "requires_clinical_language_review_before_pilot"
    assert "myocardial infarction, heart attack, mi, दिल का दौरा" in rules


def test_synonym_loader_rejects_unsafe_or_single_term_entries(tmp_path: Path) -> None:
    path = tmp_path / "synonyms.json"
    path.write_text('{"entries":[{"terms":["only"]}]}', encoding="utf-8")
    with pytest.raises(InvalidSynonymConfiguration):
        load_synonym_rules(path)
