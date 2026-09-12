"""Abandoned direct-upload expiry worker tests."""

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from uuid import uuid4

import pytest

from app.documents.cleanup import PostgresAbandonedUploadCleaner


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

    def transaction(self) -> _Context:
        return _Context(self)

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.executions.append((query, args))
        return self.rows

    async def execute(self, query: str, *args: Any) -> None:
        self.executions.append((query, args))


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def acquire(self) -> _Context:
        return _Context(self.connection)


@pytest.mark.asyncio
async def test_expiry_cancels_initiated_rows_and_emits_reference_only_events() -> None:
    document_id = uuid4()
    tenant_id = uuid4()
    connection = _Connection(
        [{"id": document_id, "tenant_id": tenant_id, "version": 2}]
    )
    cleaner = PostgresAbandonedUploadCleaner(_Pool(connection))

    expired = await cleaner.expire(now=datetime.now(UTC), limit=10)

    assert expired[0].document_id == document_id
    update_query, _update_args = connection.executions[0]
    assert "FOR UPDATE SKIP LOCKED" in update_query
    event_query, event_args = connection.executions[1]
    assert "DocumentUploadExpired.v1" in event_query
    assert str(document_id) in str(event_args)
    assert "patient" not in str(event_args).lower()
