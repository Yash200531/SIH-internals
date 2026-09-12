"""Safe Elasticsearch request construction and opaque cursor handling."""

import base64
import json
from pathlib import Path
from typing import TypeAlias

from app.search.contracts import ClinicalSearchQuery

CursorValue: TypeAlias = str | int | float

_CURSOR_VERSION = 1
_SOURCE_FIELDS = [
    "record_id",
    "tenant_id",
    "facility_id",
    "patient_id",
    "encounter_id",
    "document_id",
    "source_kind",
    "source_id",
    "title",
    "entity_type",
    "statement_status",
    "occurred_at",
]


class InvalidSearchCursor(ValueError):
    pass


class InvalidSynonymConfiguration(ValueError):
    pass


def encode_cursor(sort_values: list[CursorValue]) -> str:
    if not 1 <= len(sort_values) <= 4 or any(
        isinstance(value, bool) or not isinstance(value, (str, int, float))
        for value in sort_values
    ):
        raise InvalidSearchCursor("invalid search sort values")
    payload = json.dumps(
        {"v": _CURSOR_VERSION, "sort": sort_values},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(cursor: str) -> list[CursorValue]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
        payload = json.loads(raw)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidSearchCursor("invalid search cursor") from exc
    if not isinstance(payload, dict) or payload.get("v") != _CURSOR_VERSION:
        raise InvalidSearchCursor("unsupported search cursor")
    values = payload.get("sort")
    if (
        not isinstance(values, list)
        or not 1 <= len(values) <= 4
        or any(
            isinstance(value, bool) or not isinstance(value, (str, int, float))
            for value in values
        )
    ):
        raise InvalidSearchCursor("invalid search cursor values")
    return values


def build_search_request(criteria: ClinicalSearchQuery) -> dict[str, object]:
    filters: list[dict[str, object]] = [
        {"term": {"tenant_id": str(criteria.tenant_id)}},
        {"term": {"patient_id": str(criteria.patient_id)}},
        {"terms": {"facility_id": [str(value) for value in criteria.facility_ids]}},
        {"term": {"security_labels": "human-reviewed"}},
    ]
    if criteria.source_kind:
        filters.append({"term": {"source_kind": criteria.source_kind.value}})
    if criteria.entity_type:
        filters.append({"term": {"entity_type": criteria.entity_type}})
    if criteria.from_date or criteria.to_date:
        bounds: dict[str, str] = {}
        if criteria.from_date:
            bounds["gte"] = criteria.from_date.isoformat()
        if criteria.to_date:
            bounds["lte"] = criteria.to_date.isoformat()
        filters.append({"range": {"occurred_at": bounds}})

    must: list[dict[str, object]] = []
    if criteria.q:
        must.append(
            {
                "multi_match": {
                    "query": criteria.q,
                    "fields": ["title^3", "content"],
                    "type": "best_fields",
                    "operator": "and",
                }
            }
        )

    request: dict[str, object] = {
        "size": criteria.page_size,
        "track_total_hits": True,
        "_source": _SOURCE_FIELDS,
        "query": {"bool": {"filter": filters, "must": must}},
        "sort": (
            [{"_score": "desc"}, {"occurred_at": "desc"}, {"record_id": "asc"}]
            if criteria.q
            else [{"occurred_at": "desc"}, {"record_id": "asc"}]
        ),
        "aggs": {
            "source_kinds": {"terms": {"field": "source_kind", "size": 10}},
            "entity_types": {"terms": {"field": "entity_type", "size": 25}},
        },
    }
    if criteria.q:
        request["highlight"] = {
            "fields": {"title": {}, "content": {}},
            "fragment_size": 160,
            "number_of_fragments": 2,
            "pre_tags": ["<mark>"],
            "post_tags": ["</mark>"],
        }
    if criteria.cursor:
        request["search_after"] = decode_cursor(criteria.cursor)
    return request


def load_synonym_rules(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidSynonymConfiguration("cannot read synonym configuration") from exc
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not entries:
        raise InvalidSynonymConfiguration("synonym entries are required")
    rules: list[str] = []
    for entry in entries:
        terms = entry.get("terms") if isinstance(entry, dict) else None
        if (
            not isinstance(terms, list)
            or len(terms) < 2
            or any(
                not isinstance(term, str)
                or not term.strip()
                or "," in term
                or "\n" in term
                for term in terms
            )
        ):
            raise InvalidSynonymConfiguration("each synonym entry needs safe terms")
        normalized = list(dict.fromkeys(term.strip().lower() for term in terms))
        if len(normalized) < 2:
            raise InvalidSynonymConfiguration("synonym terms must be distinct")
        rules.append(", ".join(normalized))
    return rules
