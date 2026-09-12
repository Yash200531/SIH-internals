"""Elasticsearch adapter for the rebuildable Phase 9 clinical projection."""

import html
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.search.contracts import (
    ClinicalSearchHit,
    ClinicalSearchQuery,
    ClinicalSearchRecord,
    ClinicalSearchResponse,
    SearchFacets,
    SearchHighlight,
)
from app.search.query import build_search_request, encode_cursor


class SearchIndexError(RuntimeError):
    pass


@dataclass(frozen=True)
class RebuildResult:
    index_name: str
    indexed_count: int
    previous_indexes: tuple[str, ...]


@dataclass(frozen=True)
class TenantReconciliationResult:
    canonical_count: int
    indexed_count: int
    missing_record_ids: tuple[str, ...]
    unexpected_record_ids: tuple[str, ...]

    @property
    def matches(self) -> bool:
        return not self.missing_record_ids and not self.unexpected_record_ids


def build_index_definition(synonym_rules: list[str]) -> dict[str, object]:
    if not synonym_rules:
        raise ValueError("at least one reviewed synonym rule is required")
    return {
        "settings": {
            "index": {"number_of_shards": 1, "number_of_replicas": 0},
            "analysis": {
                "filter": {
                    "medikiosk_ascii": {
                        "type": "asciifolding",
                        "preserve_original": True,
                    },
                    "medikiosk_synonyms": {
                        "type": "synonym_graph",
                        "lenient": False,
                        "expand": True,
                        "synonyms": synonym_rules,
                    }
                },
                "analyzer": {
                    "medikiosk_index": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase", "medikiosk_ascii"],
                    },
                    "medikiosk_search": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": [
                            "lowercase",
                            "medikiosk_synonyms",
                            "medikiosk_ascii",
                        ],
                    },
                },
            },
        },
        "mappings": {
            "dynamic": "strict",
            "properties": {
                "record_id": {"type": "keyword"},
                "tenant_id": {"type": "keyword"},
                "facility_id": {"type": "keyword"},
                "patient_id": {"type": "keyword"},
                "encounter_id": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                "source_kind": {"type": "keyword"},
                "source_id": {"type": "keyword"},
                "title": {
                    "type": "text",
                    "analyzer": "medikiosk_index",
                    "search_analyzer": "medikiosk_search",
                },
                "content": {
                    "type": "text",
                    "analyzer": "medikiosk_index",
                    "search_analyzer": "medikiosk_search",
                },
                "entity_type": {"type": "keyword"},
                "statement_status": {"type": "keyword"},
                "occurred_at": {"type": "date"},
                "security_labels": {"type": "keyword"},
            },
        },
    }


class ElasticsearchClinicalSearchStore:
    def __init__(
        self,
        client: Any,
        *,
        alias: str,
        synonym_rules: list[str],
    ) -> None:
        if not alias or not alias.replace("-", "").replace("_", "").isalnum():
            raise ValueError("invalid search index alias")
        self._client = client
        self.alias = alias
        self._definition = build_index_definition(synonym_rules)

    async def ready(self) -> bool:
        return bool(await self._client.ping())

    async def ensure_index(self) -> str:
        if await self._client.indices.exists_alias(name=self.alias):
            aliases = _body(await self._client.indices.get_alias(name=self.alias))
            return sorted(aliases)[0]
        index_name = self._new_index_name()
        await self._create_index(index_name, with_alias=True)
        return index_name

    async def upsert(self, record: ClinicalSearchRecord) -> None:
        await self.ensure_index()
        await self._client.index(
            index=self.alias,
            id=record.record_id,
            document=record.model_dump(mode="json", exclude_none=True),
            refresh="wait_for",
        )

    async def bulk_upsert(
        self, records: list[ClinicalSearchRecord], *, index_name: str | None = None
    ) -> int:
        if not records:
            return 0
        target = index_name or self.alias
        if index_name is None:
            await self.ensure_index()
        operations: list[dict[str, object]] = []
        for record in records:
            operations.append({"index": {"_index": target, "_id": record.record_id}})
            operations.append(record.model_dump(mode="json", exclude_none=True))
        response = _body(
            await self._client.bulk(operations=operations, refresh="wait_for")
        )
        if response.get("errors"):
            raise SearchIndexError("one or more clinical search records failed to index")
        return len(records)

    async def delete_record(self, record_id: str) -> None:
        await self._client.options(ignore_status=[404]).delete(
            index=self.alias,
            id=record_id,
            refresh="wait_for",
        )

    async def replace_document_records(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        records: list[ClinicalSearchRecord],
    ) -> int:
        await self.ensure_index()
        await self._client.delete_by_query(
            index=self.alias,
            query={
                "bool": {
                    "filter": [
                        {"term": {"tenant_id": str(tenant_id)}},
                        {"term": {"document_id": str(document_id)}},
                    ]
                }
            },
            conflicts="proceed",
            refresh=True,
        )
        return await self.bulk_upsert(records)

    async def replace_tenant_records(
        self, *, tenant_id: UUID, records: list[ClinicalSearchRecord]
    ) -> int:
        if any(record.tenant_id != tenant_id for record in records):
            raise ValueError("tenant rebuild records must share the requested tenant")
        await self.ensure_index()
        await self._client.delete_by_query(
            index=self.alias,
            query={"term": {"tenant_id": str(tenant_id)}},
            conflicts="proceed",
            refresh=True,
        )
        indexed_count = await self.bulk_upsert(records)
        count_response = _body(
            await self._client.count(
                index=self.alias,
                query={"term": {"tenant_id": str(tenant_id)}},
            )
        )
        if int(count_response.get("count", 0)) != indexed_count:
            raise SearchIndexError("tenant rebuild count does not match canonical source")
        return indexed_count

    async def reconcile_tenant(
        self, *, tenant_id: UUID, canonical_record_ids: set[str]
    ) -> TenantReconciliationResult:
        """Compare canonical IDs with the derived index without reading narrative."""
        indexed_ids: set[str] = set()
        if not await self._client.indices.exists_alias(name=self.alias):
            return TenantReconciliationResult(
                canonical_count=len(canonical_record_ids),
                indexed_count=0,
                missing_record_ids=tuple(sorted(canonical_record_ids)),
                unexpected_record_ids=(),
            )
        after: dict[str, object] | None = None
        while True:
            composite: dict[str, object] = {
                "size": 500,
                "sources": [{"record_id": {"terms": {"field": "record_id"}}}],
            }
            if after is not None:
                composite["after"] = after
            response = _body(
                await self._client.search(
                    index=self.alias,
                    size=0,
                    query={"term": {"tenant_id": str(tenant_id)}},
                    aggregations={"record_ids": {"composite": composite}},
                )
            )
            aggregation = response.get("aggregations", {}).get("record_ids", {})
            if not isinstance(aggregation, dict):
                raise SearchIndexError("reconciliation aggregation is missing")
            buckets = aggregation.get("buckets", [])
            if not isinstance(buckets, list):
                raise SearchIndexError("reconciliation buckets are invalid")
            for bucket in buckets:
                key = bucket.get("key", {}) if isinstance(bucket, dict) else {}
                record_id = key.get("record_id") if isinstance(key, dict) else None
                if isinstance(record_id, str):
                    indexed_ids.add(record_id)
            next_after = aggregation.get("after_key")
            if not buckets or not isinstance(next_after, dict):
                break
            after = next_after
        return TenantReconciliationResult(
            canonical_count=len(canonical_record_ids),
            indexed_count=len(indexed_ids),
            missing_record_ids=tuple(sorted(canonical_record_ids - indexed_ids)),
            unexpected_record_ids=tuple(sorted(indexed_ids - canonical_record_ids)),
        )

    async def search(self, criteria: ClinicalSearchQuery) -> ClinicalSearchResponse:
        await self.ensure_index()
        response = _body(
            await self._client.search(
                index=self.alias,
                **build_search_request(criteria),
            )
        )
        raw_hits = response.get("hits", {}).get("hits", [])
        hits = [_hit(item, criteria) for item in raw_hits]
        total_value = response.get("hits", {}).get("total", 0)
        total = (
            int(total_value.get("value", 0))
            if isinstance(total_value, dict)
            else int(total_value)
        )
        next_cursor = None
        if len(raw_hits) == criteria.page_size and raw_hits[-1].get("sort"):
            next_cursor = encode_cursor(raw_hits[-1]["sort"])
        aggregations = response.get("aggregations", {})
        return ClinicalSearchResponse(
            total=total,
            hits=hits,
            facets=SearchFacets(
                source_kinds=_buckets(aggregations.get("source_kinds", {})),
                entity_types=_buckets(aggregations.get("entity_types", {})),
            ),
            took_ms=max(0, int(response.get("took", 0))),
            next_cursor=next_cursor,
        )

    async def rebuild(self, records: list[ClinicalSearchRecord]) -> RebuildResult:
        previous_indexes: tuple[str, ...] = ()
        if await self._client.indices.exists_alias(name=self.alias):
            aliases = _body(await self._client.indices.get_alias(name=self.alias))
            previous_indexes = tuple(sorted(aliases))
        index_name = self._new_index_name()
        await self._create_index(index_name, with_alias=False)
        try:
            await self.bulk_upsert(records, index_name=index_name)
            count_response = _body(
                await self._client.count(index=index_name, query={"match_all": {}})
            )
            indexed_count = int(count_response.get("count", 0))
            if indexed_count != len(records):
                raise SearchIndexError("rebuilt index count does not match canonical source")
            actions: list[dict[str, object]] = [
                {"remove": {"index": old, "alias": self.alias}}
                for old in previous_indexes
            ]
            actions.append({"add": {"index": index_name, "alias": self.alias}})
            await self._client.indices.update_aliases(actions=actions)
        except Exception:
            await self._client.indices.delete(index=index_name, ignore_unavailable=True)
            raise
        return RebuildResult(index_name, indexed_count, previous_indexes)

    async def close(self) -> None:
        await self._client.close()

    async def _create_index(self, index_name: str, *, with_alias: bool) -> None:
        aliases = {self.alias: {"is_write_index": True}} if with_alias else None
        await self._client.indices.create(
            index=index_name,
            settings=self._definition["settings"],
            mappings=self._definition["mappings"],
            aliases=aliases,
        )

    def _new_index_name(self) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        return f"{self.alias}-v1-{timestamp}-{uuid4().hex[:8]}"


def _body(response: Any) -> dict[str, Any]:
    value = response.body if hasattr(response, "body") else response
    if not isinstance(value, dict):
        raise SearchIndexError("Elasticsearch returned an invalid response")
    return value


def _hit(item: dict[str, Any], criteria: ClinicalSearchQuery) -> ClinicalSearchHit:
    source = item.get("_source")
    if not isinstance(source, dict):
        raise SearchIndexError("search hit is missing its source")
    if (
        source.get("tenant_id") != str(criteria.tenant_id)
        or source.get("patient_id") != str(criteria.patient_id)
        or source.get("facility_id")
        not in {str(facility_id) for facility_id in criteria.facility_ids}
    ):
        raise SearchIndexError("search backend returned a record outside authorized scope")
    highlights: list[SearchHighlight] = []
    highlight_payload = item.get("highlight", {})
    if isinstance(highlight_payload, dict):
        for field in ("title", "content"):
            fragments = highlight_payload.get(field, [])
            if isinstance(fragments, list):
                safe = [_safe_fragment(str(fragment)) for fragment in fragments[:2]]
                if safe:
                    highlights.append(SearchHighlight(field=field, fragments=safe))
    public_source = {key: value for key, value in source.items() if key != "tenant_id"}
    return ClinicalSearchHit.model_validate({**public_source, "highlights": highlights})


def _safe_fragment(fragment: str) -> str:
    escaped = html.escape(fragment, quote=True)
    return escaped.replace("&lt;mark&gt;", "<mark>").replace("&lt;/mark&gt;", "</mark>")


def _buckets(aggregation: Any) -> dict[str, int]:
    buckets = aggregation.get("buckets", []) if isinstance(aggregation, dict) else []
    return {
        str(bucket["key"]): int(bucket["doc_count"])
        for bucket in buckets
        if isinstance(bucket, dict) and "key" in bucket and "doc_count" in bucket
    }
