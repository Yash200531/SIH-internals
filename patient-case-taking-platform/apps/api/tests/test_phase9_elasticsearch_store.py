from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.search.contracts import ClinicalSearchQuery, ClinicalSearchRecord, SourceKind
from app.search.elasticsearch_store import (
    ElasticsearchClinicalSearchStore,
    SearchIndexError,
    build_index_definition,
)


class FakeIndices:
    def __init__(self) -> None:
        self.aliases: dict[str, dict] = {}
        self.created: list[dict] = []
        self.alias_actions: list[dict] = []
        self.deleted: list[str] = []

    async def exists_alias(self, *, name: str) -> bool:
        return bool(self.aliases)

    async def get_alias(self, *, name: str):
        return self.aliases

    async def create(self, **kwargs):
        self.created.append(kwargs)
        aliases = kwargs.get("aliases")
        if aliases:
            self.aliases[kwargs["index"]] = {"aliases": aliases}
        return {"acknowledged": True}

    async def update_aliases(self, *, actions: list[dict]):
        self.alias_actions = actions
        for action in actions:
            if "remove" in action:
                self.aliases.pop(action["remove"]["index"], None)
            if "add" in action:
                self.aliases[action["add"]["index"]] = {
                    "aliases": {action["add"]["alias"]: {}}
                }
        return {"acknowledged": True}

    async def delete(self, *, index: str, ignore_unavailable: bool):
        self.deleted.append(index)
        return {"acknowledged": True}


class FakeClient:
    def __init__(self) -> None:
        self.indices = FakeIndices()
        self.bulk_calls: list[dict] = []
        self.index_calls: list[dict] = []
        self.delete_by_query_calls: list[dict] = []
        self.search_call: dict | None = None
        self.bulk_errors = False
        self.count_value: int | None = None
        self.result_record: ClinicalSearchRecord | None = None
        self.reconciliation_ids: list[str] = []
        self.closed = False

    def options(self, **_kwargs):
        return self

    async def ping(self) -> bool:
        return True

    async def index(self, **kwargs):
        self.index_calls.append(kwargs)
        return {"result": "created"}

    async def bulk(self, **kwargs):
        self.bulk_calls.append(kwargs)
        return {"errors": self.bulk_errors, "items": []}

    async def delete(self, **kwargs):
        return {"result": "not_found"}

    async def delete_by_query(self, **kwargs):
        self.delete_by_query_calls.append(kwargs)
        return {"deleted": 1}

    async def count(self, **kwargs):
        if self.count_value is not None:
            return {"count": self.count_value}
        operations = self.bulk_calls[-1]["operations"] if self.bulk_calls else []
        return {"count": len(operations) // 2}

    async def search(self, **kwargs):
        self.search_call = kwargs
        if "record_ids" in kwargs.get("aggregations", {}):
            return {
                "aggregations": {
                    "record_ids": {
                        "buckets": [
                            {"key": {"record_id": record_id}, "doc_count": 1}
                            for record_id in self.reconciliation_ids
                        ]
                    }
                }
            }
        result_record = self.result_record or _record()
        return {
            "took": 7,
            "hits": {
                "total": {"value": 1, "relation": "eq"},
                "hits": [
                    {
                        "_source": result_record.model_dump(mode="json", exclude_none=True),
                        "highlight": {
                            "content": ["<script>x</script> <mark>pain</mark>"]
                        },
                        "sort": [0.9, "2026-09-05T10:00:00Z", "summary:one"],
                    }
                ],
            },
            "aggregations": {
                "source_kinds": {
                    "buckets": [{"key": "signed_summary", "doc_count": 1}]
                },
                "entity_types": {"buckets": []},
            },
        }

    async def close(self):
        self.closed = True


def _record(**updates) -> ClinicalSearchRecord:
    source_id = uuid4()
    values = {
        "record_id": f"summary:{source_id}",
        "tenant_id": uuid4(),
        "facility_id": uuid4(),
        "patient_id": uuid4(),
        "encounter_id": uuid4(),
        "source_kind": SourceKind.SIGNED_SUMMARY,
        "source_id": source_id,
        "title": "Chest pain",
        "content": "Pain started today",
        "occurred_at": datetime.now(UTC),
        "security_labels": ["human-reviewed", "restricted"],
    }
    values.update(updates)
    return ClinicalSearchRecord(**values)


def _store(client: FakeClient) -> ElasticsearchClinicalSearchStore:
    return ElasticsearchClinicalSearchStore(
        client,
        alias="medikiosk-clinical-search",
        synonym_rules=["myocardial infarction, heart attack, mi"],
    )


def test_index_definition_is_strict_and_uses_search_time_synonyms() -> None:
    definition = build_index_definition(["myocardial infarction, heart attack, mi"])
    mappings = definition["mappings"]
    analysis = definition["settings"]["analysis"]

    assert mappings["dynamic"] == "strict"
    assert mappings["properties"]["tenant_id"] == {"type": "keyword"}
    assert mappings["properties"]["content"]["analyzer"] == "medikiosk_index"
    assert mappings["properties"]["content"]["search_analyzer"] == "medikiosk_search"
    assert analysis["filter"]["medikiosk_synonyms"]["type"] == "synonym_graph"
    assert analysis["filter"]["medikiosk_ascii"]["preserve_original"] is True


@pytest.mark.asyncio
async def test_ensure_index_creates_versioned_backing_alias() -> None:
    client = FakeClient()
    index_name = await _store(client).ensure_index()

    assert index_name.startswith("medikiosk-clinical-search-v1-")
    assert client.indices.created[0]["aliases"] == {
        "medikiosk-clinical-search": {"is_write_index": True}
    }


@pytest.mark.asyncio
async def test_bulk_upsert_uses_stable_ids_and_rejects_partial_errors() -> None:
    client = FakeClient()
    record = _record()
    store = _store(client)

    assert await store.bulk_upsert([record]) == 1
    operations = client.bulk_calls[0]["operations"]
    assert operations[0]["index"]["_id"] == record.record_id
    assert operations[1]["tenant_id"] == str(record.tenant_id)

    client.bulk_errors = True
    with pytest.raises(SearchIndexError, match="failed to index"):
        await store.bulk_upsert([record])


@pytest.mark.asyncio
async def test_search_parses_facets_cursor_and_escapes_source_markup() -> None:
    client = FakeClient()
    record = _record()
    client.result_record = record
    query = ClinicalSearchQuery(
        tenant_id=record.tenant_id,
        patient_id=record.patient_id,
        facility_ids=(record.facility_id,),
        q="pain",
        page_size=1,
    )
    response = await _store(client).search(query)

    assert response.total == 1
    assert response.took_ms == 7
    assert response.facets.source_kinds == {"signed_summary": 1}
    assert response.next_cursor is not None
    assert response.hits[0].highlights[0].fragments == [
        "&lt;script&gt;x&lt;/script&gt; <mark>pain</mark>"
    ]
    filters = client.search_call["query"]["bool"]["filter"]
    assert {"term": {"tenant_id": str(record.tenant_id)}} in filters


@pytest.mark.asyncio
async def test_search_rejects_backend_hit_outside_authorized_scope() -> None:
    client = FakeClient()
    requested = _record()
    client.result_record = _record(tenant_id=requested.tenant_id, patient_id=uuid4())
    query = ClinicalSearchQuery(
        tenant_id=requested.tenant_id,
        patient_id=requested.patient_id,
        facility_ids=(requested.facility_id,),
        q="pain",
    )

    with pytest.raises(SearchIndexError, match="outside authorized scope"):
        await _store(client).search(query)


@pytest.mark.asyncio
async def test_replace_document_records_deletes_only_tenant_document_scope() -> None:
    client = FakeClient()
    tenant_id, document_id = uuid4(), uuid4()
    fact = _record(
        tenant_id=tenant_id,
        document_id=document_id,
        source_kind=SourceKind.REVIEWED_FACT,
        entity_type="medication_statement",
        statement_status="document_stated",
    )

    assert await _store(client).replace_document_records(
        tenant_id=tenant_id, document_id=document_id, records=[fact]
    ) == 1
    filters = client.delete_by_query_calls[0]["query"]["bool"]["filter"]
    assert filters == [
        {"term": {"tenant_id": str(tenant_id)}},
        {"term": {"document_id": str(document_id)}},
    ]


@pytest.mark.asyncio
async def test_replace_tenant_records_is_scoped_and_rejects_mixed_tenants() -> None:
    client = FakeClient()
    tenant_id = uuid4()
    record = _record(tenant_id=tenant_id)
    store = _store(client)

    assert await store.replace_tenant_records(
        tenant_id=tenant_id, records=[record]
    ) == 1
    assert client.delete_by_query_calls[0]["query"] == {
        "term": {"tenant_id": str(tenant_id)}
    }

    with pytest.raises(ValueError, match="share the requested tenant"):
        await store.replace_tenant_records(
            tenant_id=tenant_id,
            records=[_record()],
        )


@pytest.mark.asyncio
async def test_reconcile_tenant_reports_missing_and_unexpected_ids() -> None:
    client = FakeClient()
    client.indices.aliases = {"medikiosk-clinical-search-v1-current": {"aliases": {}}}
    client.reconciliation_ids = ["summary:shared", "fact:unexpected"]

    result = await _store(client).reconcile_tenant(
        tenant_id=uuid4(),
        canonical_record_ids={"summary:shared", "fact:missing"},
    )

    assert result.matches is False
    assert result.canonical_count == 2
    assert result.indexed_count == 2
    assert result.missing_record_ids == ("fact:missing",)
    assert result.unexpected_record_ids == ("fact:unexpected",)


@pytest.mark.asyncio
async def test_reconcile_tenant_does_not_create_a_missing_index() -> None:
    client = FakeClient()

    result = await _store(client).reconcile_tenant(
        tenant_id=uuid4(), canonical_record_ids={"summary:missing"}
    )

    assert result.matches is False
    assert result.missing_record_ids == ("summary:missing",)
    assert client.indices.created == []


@pytest.mark.asyncio
async def test_rebuild_validates_count_then_atomically_swaps_alias() -> None:
    client = FakeClient()
    client.indices.aliases = {"medikiosk-clinical-search-v1-old": {"aliases": {}}}
    store = _store(client)
    record = _record()

    result = await store.rebuild([record])

    assert result.indexed_count == 1
    assert result.previous_indexes == ("medikiosk-clinical-search-v1-old",)
    assert client.indices.alias_actions[0] == {
        "remove": {
            "index": "medikiosk-clinical-search-v1-old",
            "alias": "medikiosk-clinical-search",
        }
    }
    assert "add" in client.indices.alias_actions[-1]


@pytest.mark.asyncio
async def test_rebuild_removes_failed_backing_index_without_swapping_alias() -> None:
    client = FakeClient()
    client.count_value = 0
    store = _store(client)

    with pytest.raises(SearchIndexError, match="count"):
        await store.rebuild([_record()])
    assert len(client.indices.deleted) == 1
    assert client.indices.alias_actions == []
