"""Leased, retry-bounded Kafka publisher for Phase 8 summary events."""

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

import asyncpg

from app.config import settings

_CLAIM = """
WITH ready AS (
    SELECT event_id FROM clinical_summary_outbox
    WHERE published_at IS NULL AND dead_lettered_at IS NULL
      AND next_attempt_at <= CURRENT_TIMESTAMP
      AND (publish_lease_expires_at IS NULL
           OR publish_lease_expires_at <= CURRENT_TIMESTAMP)
    ORDER BY occurred_at FOR UPDATE SKIP LOCKED LIMIT $1
)
UPDATE clinical_summary_outbox AS event
SET publish_lease_expires_at = CURRENT_TIMESTAMP + ($2 * INTERVAL '1 second')
FROM ready WHERE event.event_id = ready.event_id
RETURNING event.event_id, event.tenant_id, event.summary_id, event.event_type,
          event.event_version, event.idempotency_key, event.payload,
          event.occurred_at, event.attempt
"""

_MARK_PUBLISHED = """
UPDATE clinical_summary_outbox
SET published_at = CURRENT_TIMESTAMP, publish_lease_expires_at = NULL,
    last_error_class = NULL
WHERE event_id = $1 AND published_at IS NULL AND dead_lettered_at IS NULL
"""

_MARK_FAILED = """
UPDATE clinical_summary_outbox
SET attempt = attempt + 1, publish_lease_expires_at = NULL,
    last_error_class = $2,
    next_attempt_at = CURRENT_TIMESTAMP + ($3 * INTERVAL '1 second'),
    dead_lettered_at = CASE WHEN attempt + 1 >= $4 THEN CURRENT_TIMESTAMP ELSE NULL END
WHERE event_id = $1 AND published_at IS NULL AND dead_lettered_at IS NULL
"""


@dataclass(frozen=True)
class SummaryOutboxEvent:
    event_id: UUID
    tenant_id: UUID
    summary_id: UUID
    event_type: str
    event_version: int
    idempotency_key: str
    payload: dict[str, object]
    occurred_at: datetime
    attempt: int

    @classmethod
    def from_row(cls, row: Any) -> "SummaryOutboxEvent":
        values = dict(row)
        if isinstance(values["payload"], str):
            values["payload"] = json.loads(values["payload"])
        return cls(**values)

    def encoded(self) -> bytes:
        payload = asdict(self)
        for key in ("event_id", "tenant_id", "summary_id"):
            payload[key] = str(payload[key])
        payload["occurred_at"] = self.occurred_at.isoformat()
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


class EventTransport(Protocol):
    async def publish(self, event: SummaryOutboxEvent) -> None: ...


class PostgresSummaryOutbox:
    def __init__(self, pool: Any, *, lease_seconds: int = 30, max_attempts: int = 3) -> None:
        if lease_seconds <= 0 or max_attempts <= 0:
            raise ValueError("Outbox lease and attempt limits must be positive")
        self._pool = pool
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts

    async def claim(self, *, limit: int) -> list[SummaryOutboxEvent]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(_CLAIM, limit, self._lease_seconds)
        return [SummaryOutboxEvent.from_row(row) for row in rows]

    async def mark_published(self, event_id: UUID) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(_MARK_PUBLISHED, event_id)

    async def mark_failed(self, event_id: UUID, error_class: str, attempt: int) -> None:
        if not error_class or len(error_class) > 128:
            error_class = "publisher_error"
        backoff_seconds = min(60, 2 ** min(attempt, 6))
        async with self._pool.acquire() as connection:
            await connection.execute(
                _MARK_FAILED, event_id, error_class, backoff_seconds, self._max_attempts
            )


class KafkaEventTransport:
    def __init__(self, producer: Any, topic: str) -> None:
        self._producer = producer
        self._topic = topic

    async def publish(self, event: SummaryOutboxEvent) -> None:
        await self._producer.send_and_wait(
            self._topic,
            event.encoded(),
            key=str(event.summary_id).encode(),
            headers=[
                ("event_type", event.event_type.encode()),
                ("tenant_id", str(event.tenant_id).encode()),
            ],
        )


async def publish_once(
    outbox: PostgresSummaryOutbox, transport: EventTransport, *, batch_size: int
) -> int:
    events = await outbox.claim(limit=batch_size)
    published = 0
    for event in events:
        try:
            await transport.publish(event)
        except Exception as exc:
            await outbox.mark_failed(event.event_id, type(exc).__name__, event.attempt + 1)
            continue
        await outbox.mark_published(event.event_id)
        published += 1
    return published


async def _run() -> None:
    parser = argparse.ArgumentParser(description="Publish MediKiosk summary events")
    parser.add_argument("command", choices=("once", "forever"))
    args = parser.parse_args()
    if not settings.DATABASE_MAINTENANCE_URL:
        raise RuntimeError("DATABASE_MAINTENANCE_URL is required for outbox publishing")
    from aiokafka import AIOKafkaProducer

    pool = await asyncpg.create_pool(settings.DATABASE_MAINTENANCE_URL, min_size=1, max_size=4)
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_BROKERS,
        acks="all",
        enable_idempotence=True,
        client_id="medikiosk-summary-outbox",
    )
    await producer.start()
    outbox = PostgresSummaryOutbox(
        pool,
        lease_seconds=settings.SUMMARY_OUTBOX_LEASE_SECONDS,
        max_attempts=settings.SUMMARY_OUTBOX_MAX_ATTEMPTS,
    )
    transport = KafkaEventTransport(producer, settings.SUMMARY_EVENT_TOPIC)
    try:
        while True:
            count = await publish_once(
                outbox, transport, batch_size=settings.SUMMARY_OUTBOX_BATCH_SIZE
            )
            print(f"Published {count} summary event(s)")
            if args.command == "once":
                return
            await asyncio.sleep(settings.SUMMARY_OUTBOX_POLL_INTERVAL_SECONDS)
    finally:
        await producer.stop()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_run())
