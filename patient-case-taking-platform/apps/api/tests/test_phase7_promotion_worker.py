"""Batch-isolation tests for the reviewed-fact promotion worker."""

from uuid import uuid4

import pytest

from app.documents.promotion_worker import ReadyPromotion, run_once


class _Queue:
    def __init__(self, items: list[ReadyPromotion]) -> None:
        self.items = items

    async def ready(self, *, limit: int) -> list[ReadyPromotion]:
        return self.items[:limit]


class _Processor:
    def __init__(self, failed_document_id) -> None:
        self.failed_document_id = failed_document_id
        self.calls = []

    async def promote(self, **scope: object) -> None:
        self.calls.append(scope)
        if scope["document_id"] == self.failed_document_id:
            raise RuntimeError("synthetic failure")


@pytest.mark.asyncio
async def test_one_failed_promotion_does_not_block_the_batch() -> None:
    tenant_id = uuid4()
    actor_id = uuid4()
    failed_id = uuid4()
    successful_id = uuid4()
    queue = _Queue(
        [
            ReadyPromotion(uuid4(), tenant_id, failed_id, actor_id, "doctor"),
            ReadyPromotion(uuid4(), tenant_id, successful_id, actor_id, "doctor"),
        ]
    )
    processor = _Processor(failed_id)

    processed = await run_once(queue, processor, batch_size=10)

    assert processed == 1
    assert [call["document_id"] for call in processor.calls] == [
        failed_id,
        successful_id,
    ]
