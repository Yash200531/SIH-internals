"""Validated Kafka event boundary for the clinical search projection."""

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Protocol
from uuid import UUID

from app.search.contracts import ClinicalSearchRecord


class SearchProjectionEventType(StrEnum):
    SUMMARY_SIGNED = "clinical.summary.signed.v1"
    DOCUMENT_FACTS_PROMOTED = "ReviewedDocumentFactsPromoted.v1"
    DOCUMENT_FACTS_WITHDRAWN = "ReviewedDocumentFactsWithdrawn.v1"


class InvalidSearchProjectionEvent(ValueError):
    pass


@dataclass(frozen=True)
class SearchProjectionEvent:
    event_id: UUID
    tenant_id: UUID
    aggregate_id: UUID
    event_type: SearchProjectionEventType
    event_version: int


class ProjectionRepository(Protocol):
    async def get_signed_summary_record(
        self, *, tenant_id: UUID, summary_id: UUID
    ) -> ClinicalSearchRecord | None: ...

    async def list_document_fact_records(
        self, *, tenant_id: UUID, document_id: UUID
    ) -> list[ClinicalSearchRecord]: ...


class ProjectionStore(Protocol):
    async def upsert(self, record: ClinicalSearchRecord) -> None: ...

    async def delete_record(self, record_id: str) -> None: ...

    async def replace_document_records(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        records: list[ClinicalSearchRecord],
    ) -> int: ...


class ClinicalSearchProjector:
    def __init__(self, repository: ProjectionRepository, store: ProjectionStore) -> None:
        self._repository = repository
        self._store = store

    async def project(self, event: SearchProjectionEvent) -> int:
        if event.event_type is SearchProjectionEventType.SUMMARY_SIGNED:
            record = await self._repository.get_signed_summary_record(
                tenant_id=event.tenant_id,
                summary_id=event.aggregate_id,
            )
            if record is None:
                await self._store.delete_record(f"summary:{event.aggregate_id}")
                return 0
            await self._store.upsert(record)
            return 1

        records = await self._repository.list_document_fact_records(
            tenant_id=event.tenant_id,
            document_id=event.aggregate_id,
        )
        return await self._store.replace_document_records(
            tenant_id=event.tenant_id,
            document_id=event.aggregate_id,
            records=records,
        )


def parse_projection_event(
    value: bytes,
    *,
    topic: str,
    summary_topic: str,
    document_topic: str,
) -> SearchProjectionEvent | None:
    try:
        decoded = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidSearchProjectionEvent("event value must be UTF-8 JSON") from exc
    if not isinstance(decoded, dict):
        raise InvalidSearchProjectionEvent("event value must be a JSON object")

    raw_type = decoded.get("event_type")
    if not isinstance(raw_type, str):
        raise InvalidSearchProjectionEvent("event_type is required")

    if topic == summary_topic:
        if raw_type != SearchProjectionEventType.SUMMARY_SIGNED:
            return None
        aggregate_key = "summary_id"
    elif topic == document_topic:
        if raw_type not in {
            SearchProjectionEventType.DOCUMENT_FACTS_PROMOTED,
            SearchProjectionEventType.DOCUMENT_FACTS_WITHDRAWN,
        }:
            return None
        aggregate_key = "aggregate_id"
    else:
        raise InvalidSearchProjectionEvent("event arrived on an unexpected topic")

    event_version = decoded.get("event_version")
    if type(event_version) is not int or event_version != 1:
        raise InvalidSearchProjectionEvent("only event_version 1 is supported")
    event_id = _uuid(decoded, "event_id")
    tenant_id = _uuid(decoded, "tenant_id")
    aggregate_id = _uuid(decoded, aggregate_key)

    payload = decoded.get("payload")
    if not isinstance(payload, Mapping):
        raise InvalidSearchProjectionEvent("payload must be an object")
    payload_identifier = "summary_id" if aggregate_key == "summary_id" else "document_id"
    if payload_identifier in payload:
        try:
            payload_id = UUID(str(payload[payload_identifier]))
        except (TypeError, ValueError) as exc:
            raise InvalidSearchProjectionEvent(
                f"payload {payload_identifier} is invalid"
            ) from exc
        if payload_id != aggregate_id:
            raise InvalidSearchProjectionEvent(
                f"payload {payload_identifier} does not match aggregate"
            )

    return SearchProjectionEvent(
        event_id=event_id,
        tenant_id=tenant_id,
        aggregate_id=aggregate_id,
        event_type=SearchProjectionEventType(raw_type),
        event_version=event_version,
    )


def _uuid(payload: Mapping[str, Any], key: str) -> UUID:
    try:
        return UUID(str(payload[key]))
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidSearchProjectionEvent(f"{key} is invalid") from exc
