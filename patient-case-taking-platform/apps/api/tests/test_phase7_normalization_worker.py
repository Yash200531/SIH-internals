"""Durable page-normalization queue worker tests."""

from uuid import uuid4

import pytest

from app.documents.normalization_worker import ReadyDocument, run_once


class _Queue:
    def __init__(self, ready: list[ReadyDocument]) -> None:
        self.documents = ready

    async def ready(self, *, limit: int) -> list[ReadyDocument]:
        return self.documents[:limit]


class _Processor:
    def __init__(self, failing_id=None) -> None:
        self.failing_id = failing_id
        self.calls: list[dict[str, object]] = []

    async def process(self, **values: object) -> None:
        self.calls.append(values)
        if values["document_id"] == self.failing_id:
            raise ValueError("synthetic concurrent worker")


@pytest.mark.asyncio
async def test_worker_processes_scan_passed_documents_and_isolates_conflicts() -> None:
    first = ReadyDocument(uuid4(), uuid4(), 5)
    second = ReadyDocument(uuid4(), uuid4(), 5)
    processor = _Processor(failing_id=first.document_id)

    processed = await run_once(_Queue([first, second]), processor, batch_size=10)

    assert processed == 1
    assert [call["document_id"] for call in processor.calls] == [
        first.document_id,
        second.document_id,
    ]
