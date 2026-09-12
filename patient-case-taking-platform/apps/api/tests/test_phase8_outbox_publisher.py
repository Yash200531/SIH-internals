"""Delivery, privacy and retry tests for Phase 8 summary events."""

import json
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from uuid import uuid4

import pytest

from app.summary_workflow.outbox_publisher import (
    PostgresSummaryOutbox,
    SummaryOutboxEvent,
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
        "summary_id": uuid4(),
        "event_type": "clinical.summary.signed.v1",
        "event_version": 1,
        "idempotency_key": "summary:3:signed",
        "payload": json.dumps({"status": "signed", "lock_version": 3}),
        "occurred_at": datetime.now(UTC),
        "attempt": 0,
    }


@pytest.mark.asyncio
async def test_claim_is_leased_and_skip_locked() -> None:
    connection = _Connection([_row()])
    outbox = PostgresSummaryOutbox(_Pool(connection), lease_seconds=17)
    assert len(await outbox.claim(limit=5)) == 1
    query, args = connection.executions[0]
    assert "FOR UPDATE SKIP LOCKED" in query
    assert args == (5, 17)


def test_event_envelope_contains_metadata_only() -> None:
    payload = json.loads(SummaryOutboxEvent.from_row(_row()).encoded())
    assert payload["event_type"] == "clinical.summary.signed.v1"
    assert "content" not in payload["payload"]
    assert "chief_complaint" not in payload["payload"]


class _Outbox:
    def __init__(self, events: list[SummaryOutboxEvent]) -> None:
        self.events = events
        self.published: list[Any] = []
        self.failed: list[Any] = []

    async def claim(self, *, limit: int) -> list[SummaryOutboxEvent]:
        return self.events[:limit]

    async def mark_published(self, event_id: Any) -> None:
        self.published.append(event_id)

    async def mark_failed(self, event_id: Any, error_class: str, attempt: int) -> None:
        self.failed.append((event_id, error_class, attempt))


class _Transport:
    def __init__(self, failed: Any) -> None:
        self.failed = failed

    async def publish(self, event: SummaryOutboxEvent) -> None:
        if event.event_id == self.failed:
            raise ConnectionError("synthetic outage")


@pytest.mark.asyncio
async def test_failure_isolated_and_later_event_published() -> None:
    first = SummaryOutboxEvent.from_row(_row())
    second = SummaryOutboxEvent.from_row(_row())
    outbox = _Outbox([first, second])
    count = await publish_once(outbox, _Transport(first.event_id), batch_size=10)  # type: ignore[arg-type]
    assert count == 1
    assert outbox.published == [second.event_id]
    assert outbox.failed == [(first.event_id, "ConnectionError", 1)]
