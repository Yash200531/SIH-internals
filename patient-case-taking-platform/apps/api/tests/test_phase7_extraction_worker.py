"""Leased extraction queue worker tests."""

from uuid import uuid4

import pytest

from app.documents.extraction_worker import ReadyDocument, run_once


class _Queue:
    def __init__(self, ready: list[ReadyDocument]) -> None:
        self.documents = ready
        self.calls = 0

    async def ready(self, *, limit: int) -> list[ReadyDocument]:
        self.calls += 1
        return self.documents[:limit]


class _Processor:
    def __init__(self, failing_id=None) -> None:
        self.failing_id = failing_id
        self.calls: list[dict[str, object]] = []

    async def process(self, **values: object) -> None:
        self.calls.append(values)
        if values["document_id"] == self.failing_id:
            raise RuntimeError("synthetic infrastructure failure")


@pytest.mark.asyncio
async def test_worker_isolates_one_document_failure_and_continues_batch() -> None:
    first = ReadyDocument(uuid4(), uuid4(), 9)
    second = ReadyDocument(uuid4(), uuid4(), 9)
    processor = _Processor(failing_id=first.document_id)

    processed = await run_once(_Queue([first, second]), processor, batch_size=10)

    assert processed == 1
    assert [call["document_id"] for call in processor.calls] == [
        first.document_id,
        second.document_id,
    ]


@pytest.mark.asyncio
async def test_extraction_kill_switch_does_not_claim_or_process_work() -> None:
    queue = _Queue([ReadyDocument(uuid4(), uuid4(), 9)])
    processor = _Processor()

    processed = await run_once(
        queue,
        processor,
        batch_size=10,
        automation_enabled=False,
    )

    assert processed == 0
    assert queue.calls == 0
    assert processor.calls == []
