"""Lease, privacy and failure-isolation tests for document event publishing."""

import json
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from uuid import uuid4

import pytest

from app.documents.outbox_publisher import (
    DocumentOutboxEvent,
    PostgresDocumentOutbox,
    publish_once,
)


class _Context(AbstractAsyncContextManager):
    def __init__(self, value: Any) -> None:
        self.value = value

    async def __aenter__(self) -> Any:
        return self.value

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class _Connection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.executions: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.executions.append((query, args))
        return self.rows

    async def execute(self, query: str, *args: Any) -> str:
        self.executions.append((query, args))
        return "UPDATE 1"


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def acquire(self) -> _Context:
        return _Context(self.connection)


def _row() -> dict[str, Any]:
    return {
        "event_id": uuid4(),
        "tenant_id": uuid4(),
        "aggregate_id": uuid4(),
        "aggregate_type": "document",
        "event_type": "DocumentReviewCompleted.v1",
        "event_version": 1,
        "occurred_at": datetime.now(UTC),
        "producer": "document-review-api",
        "correlation_id": uuid4(),
        "causation_id": None,
        "data_classification": "restricted",
        "idempotency_key": "review-complete:test",
        "attempt": 0,
        "artifact_refs": "[]",
        "payload": json.dumps({"document_version": 4}),
    }


@pytest.mark.asyncio
async def test_claim_uses_skip_locked_and_a_bounded_lease() -> None:
    connection = _Connection([_row()])
    outbox = PostgresDocumentOutbox(_Pool(connection), lease_seconds=17)

    events = await outbox.claim(limit=5)

    assert len(events) == 1
    query, args = connection.executions[0]
    assert "FOR UPDATE SKIP LOCKED" in query
    assert "publish_lease_expires_at" in query
    assert args == (5, 17)


def test_event_encoding_is_a_versioned_reference_only_envelope() -> None:
    event = DocumentOutboxEvent.from_row(_row())

    payload = json.loads(event.encoded())

    assert payload["event_type"] == "DocumentReviewCompleted.v1"
    assert payload["event_version"] == 1
    assert payload["artifact_refs"] == []
    assert "raw_ocr" not in payload
    assert "document_bytes" not in payload


class _Outbox:
    def __init__(self, events: list[DocumentOutboxEvent]) -> None:
        self.events = events
        self.published: list = []
        self.failed: list = []

    async def claim(self, *, limit: int) -> list[DocumentOutboxEvent]:
        return self.events[:limit]

    async def mark_published(self, event_id) -> None:
        self.published.append(event_id)

    async def mark_failed(self, event_id, error_class: str, attempt: int) -> None:
        self.failed.append((event_id, error_class, attempt))


class _Transport:
    def __init__(self, failed_event_id) -> None:
        self.failed_event_id = failed_event_id
        self.calls: list = []

    async def publish(self, event: DocumentOutboxEvent) -> None:
        self.calls.append(event.event_id)
        if event.event_id == self.failed_event_id:
            raise ConnectionError("synthetic broker outage")


@pytest.mark.asyncio
async def test_broker_failure_is_retried_without_blocking_later_events() -> None:
    first = DocumentOutboxEvent.from_row(_row())
    second = DocumentOutboxEvent.from_row(_row())
    outbox = _Outbox([first, second])
    transport = _Transport(first.event_id)

    count = await publish_once(outbox, transport, batch_size=10)  # type: ignore[arg-type]

    assert count == 1
    assert outbox.published == [second.event_id]
    assert outbox.failed == [(first.event_id, "ConnectionError", 1)]
    assert transport.calls == [first.event_id, second.event_id]


@pytest.mark.asyncio
async def test_failure_updates_backoff_and_dead_letter_budget() -> None:
    row = _row()
    connection = _Connection([])
    outbox = PostgresDocumentOutbox(_Pool(connection), max_attempts=3)

    await outbox.mark_failed(row["event_id"], "ConnectionError", 2)

    query, args = connection.executions[0]
    assert "dead_lettered_at" in query
    assert "next_attempt_at" in query
    assert args[0] == row["event_id"]
    assert args[1] == "ConnectionError"
    assert args[3] == 3
