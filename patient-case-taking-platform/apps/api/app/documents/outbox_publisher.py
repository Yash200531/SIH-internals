"""Leased, retry-bounded Kafka publisher for the document transactional outbox."""

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
    SELECT event_id
    FROM document_outbox
    WHERE published_at IS NULL AND dead_lettered_at IS NULL
      AND next_attempt_at <= CURRENT_TIMESTAMP
      AND (
          publish_lease_expires_at IS NULL
          OR publish_lease_expires_at <= CURRENT_TIMESTAMP
      )
    ORDER BY occurred_at
    FOR UPDATE SKIP LOCKED
    LIMIT $1
)
UPDATE document_outbox AS event
SET publish_lease_expires_at = CURRENT_TIMESTAMP + ($2 * INTERVAL '1 second')
FROM ready
WHERE event.event_id = ready.event_id
RETURNING event.event_id, event.tenant_id, event.aggregate_id,
          event.aggregate_type, event.event_type, event.event_version,
          event.occurred_at, event.producer, event.correlation_id,
          event.causation_id, event.data_classification, event.idempotency_key,
          event.attempt, event.artifact_refs, event.payload
"""

_MARK_PUBLISHED = """
UPDATE document_outbox
SET published_at = CURRENT_TIMESTAMP, publish_lease_expires_at = NULL,
    last_error_class = NULL
WHERE event_id = $1 AND published_at IS NULL AND dead_lettered_at IS NULL
"""

_MARK_FAILED = """
UPDATE document_outbox
SET attempt = attempt + 1,
    publish_lease_expires_at = NULL,
    last_error_class = $2,
    next_attempt_at = CURRENT_TIMESTAMP + ($3 * INTERVAL '1 second'),
    dead_lettered_at = CASE WHEN attempt + 1 >= $4 THEN CURRENT_TIMESTAMP ELSE NULL END
WHERE event_id = $1 AND published_at IS NULL AND dead_lettered_at IS NULL
"""


@dataclass(frozen=True)
class DocumentOutboxEvent:
    event_id: UUID
    tenant_id: UUID
    aggregate_id: UUID
    aggregate_type: str
    event_type: str
    event_version: int
    occurred_at: datetime
    producer: str
    correlation_id: UUID
    causation_id: UUID | None
    data_classification: str
    idempotency_key: str
    attempt: int
    artifact_refs: list[dict[str, object]]
    payload: dict[str, object]

    @classmethod
    def from_row(cls, row: Any) -> "DocumentOutboxEvent":
        values = dict(row)
        for field in ("artifact_refs", "payload"):
            if isinstance(values[field], str):
                values[field] = json.loads(values[field])
        return cls(**values)

    def encoded(self) -> bytes:
        payload = asdict(self)
        payload["event_id"] = str(self.event_id)
        payload["tenant_id"] = str(self.tenant_id)
        payload["aggregate_id"] = str(self.aggregate_id)
        payload["correlation_id"] = str(self.correlation_id)
        payload["causation_id"] = str(self.causation_id) if self.causation_id else None
        payload["occurred_at"] = self.occurred_at.isoformat()
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


class EventTransport(Protocol):
    async def publish(self, event: DocumentOutboxEvent) -> None: ...


class PostgresDocumentOutbox:
    def __init__(
        self,
        pool: Any,
        *,
        lease_seconds: int = 30,
        max_attempts: int = 3,
    ) -> None:
        if lease_seconds <= 0 or max_attempts <= 0:
            raise ValueError("Outbox lease and attempt limits must be positive")
        self._pool = pool
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts

    async def claim(self, *, limit: int) -> list[DocumentOutboxEvent]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(_CLAIM, limit, self._lease_seconds)
        return [DocumentOutboxEvent.from_row(row) for row in rows]

    async def mark_published(self, event_id: UUID) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(_MARK_PUBLISHED, event_id)

    async def mark_failed(self, event_id: UUID, error_class: str, attempt: int) -> None:
        if not error_class or len(error_class) > 128:
            error_class = "publisher_error"
        backoff_seconds = min(60, 2 ** min(attempt, 6))
        async with self._pool.acquire() as connection:
            await connection.execute(
                _MARK_FAILED,
                event_id,
                error_class,
                backoff_seconds,
                self._max_attempts,
            )


class KafkaEventTransport:
    def __init__(self, producer: Any, topic: str) -> None:
        self._producer = producer
        self._topic = topic

    async def publish(self, event: DocumentOutboxEvent) -> None:
        await self._producer.send_and_wait(
            self._topic,
            event.encoded(),
            key=str(event.aggregate_id).encode(),
            headers=[
                ("event_type", event.event_type.encode()),
                ("tenant_id", str(event.tenant_id).encode()),
            ],
        )


async def publish_once(
    outbox: PostgresDocumentOutbox,
    transport: EventTransport,
    *,
    batch_size: int,
) -> int:
    events = await outbox.claim(limit=batch_size)
    published = 0
    for event in events:
        try:
            await transport.publish(event)
        except Exception as exc:
            await outbox.mark_failed(
                event.event_id,
                type(exc).__name__,
                event.attempt + 1,
            )
            continue
        await outbox.mark_published(event.event_id)
        published += 1
    return published


async def _run() -> None:
    parser = argparse.ArgumentParser(description="Publish MediKiosk document events")
    parser.add_argument("command", choices=("once", "forever"))
    args = parser.parse_args()
    if not settings.DATABASE_MAINTENANCE_URL:
        raise RuntimeError("DATABASE_MAINTENANCE_URL is required for outbox publishing")
    from aiokafka import AIOKafkaProducer

    pool = await asyncpg.create_pool(
        settings.DATABASE_MAINTENANCE_URL,
        min_size=1,
        max_size=4,
    )
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_BROKERS,
        acks="all",
        enable_idempotence=True,
        client_id="medikiosk-document-outbox",
    )
    await producer.start()
    outbox = PostgresDocumentOutbox(
        pool,
        lease_seconds=settings.DOCUMENT_OUTBOX_LEASE_SECONDS,
        max_attempts=settings.DOCUMENT_OUTBOX_MAX_ATTEMPTS,
    )
    transport = KafkaEventTransport(producer, settings.DOCUMENT_EVENT_TOPIC)
    try:
        while True:
            count = await publish_once(
                outbox,
                transport,
                batch_size=settings.DOCUMENT_OUTBOX_BATCH_SIZE,
            )
            print(f"Published {count} document event(s)")
            if args.command == "once":
                return
            await asyncio.sleep(settings.DOCUMENT_OUTBOX_POLL_INTERVAL_SECONDS)
    finally:
        await producer.stop()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_run())
