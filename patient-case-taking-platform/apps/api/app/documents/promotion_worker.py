"""Replay-safe worker that promotes reviewed document facts."""

import argparse
import asyncio
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import asyncpg

from app.config import settings
from app.documents.promotion import PostgresReviewedFactRepository

_READY_EVENTS = """
SELECT event.event_id, event.tenant_id, event.aggregate_id AS document_id,
       event.payload->>'reviewed_by_actor_id' AS actor_id,
       event.payload->>'reviewed_by_role' AS actor_role
FROM document_outbox AS event
WHERE event.event_type = 'DocumentReviewCompleted.v1'
  AND NOT EXISTS (
      SELECT 1 FROM document_promotion_receipt AS receipt
      WHERE receipt.tenant_id = event.tenant_id
        AND receipt.event_id = event.event_id
  )
ORDER BY event.occurred_at
LIMIT $1
"""


@dataclass(frozen=True)
class ReadyPromotion:
    event_id: UUID
    tenant_id: UUID
    document_id: UUID
    actor_id: UUID
    actor_role: str


class PromotionQueue(Protocol):
    async def ready(self, *, limit: int) -> list[ReadyPromotion]: ...


class PromotionProcessor(Protocol):
    async def promote(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        source_event_id: UUID,
        actor_id: UUID,
        actor_role: str,
    ) -> object: ...


class PostgresPromotionQueue:
    """Global outbox reader; use only with the governed maintenance role."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def ready(self, *, limit: int) -> list[ReadyPromotion]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(_READY_EVENTS, limit)
        ready: list[ReadyPromotion] = []
        for row in rows:
            if row["actor_role"] not in {"doctor", "nurse"}:
                continue
            try:
                ready.append(
                    ReadyPromotion(
                        event_id=row["event_id"],
                        tenant_id=row["tenant_id"],
                        document_id=row["document_id"],
                        actor_id=UUID(row["actor_id"]),
                        actor_role=row["actor_role"],
                    )
                )
            except (TypeError, ValueError):
                continue
        return ready


async def run_once(
    queue: PromotionQueue,
    processor: PromotionProcessor,
    *,
    batch_size: int,
) -> int:
    ready = await queue.ready(limit=batch_size)
    processed = 0
    for item in ready:
        try:
            await processor.promote(
                tenant_id=item.tenant_id,
                document_id=item.document_id,
                source_event_id=item.event_id,
                actor_id=item.actor_id,
                actor_role=item.actor_role,
            )
            processed += 1
        except Exception:
            continue
    return processed


async def _run() -> None:
    parser = argparse.ArgumentParser(description="Promote reviewed MediKiosk facts")
    parser.add_argument("command", choices=("once", "forever"))
    args = parser.parse_args()
    if not settings.DATABASE_MAINTENANCE_URL:
        raise RuntimeError("DATABASE_MAINTENANCE_URL is required for promotion")
    pool = await asyncpg.create_pool(
        settings.DATABASE_MAINTENANCE_URL,
        min_size=1,
        max_size=4,
    )
    queue = PostgresPromotionQueue(pool)
    processor = PostgresReviewedFactRepository(pool)
    try:
        while True:
            count = await run_once(
                queue,
                processor,
                batch_size=settings.DOCUMENT_PROMOTION_BATCH_SIZE,
            )
            print(f"Promoted {count} reviewed document(s)")
            if args.command == "once":
                return
            await asyncio.sleep(settings.DOCUMENT_PROMOTION_POLL_INTERVAL_SECONDS)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_run())
