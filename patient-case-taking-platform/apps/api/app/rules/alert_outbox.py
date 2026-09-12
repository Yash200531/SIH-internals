"""Fenced, bounded-retry alert outbox delivery. Kafka receipt is not staff acknowledgement."""

import argparse
import asyncio
import json
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from app.config import settings

_CLAIM = """
WITH ready AS (
 SELECT pending.id FROM triage_outbox pending
 WHERE published_at IS NULL AND dead_lettered_at IS NULL
   AND attempts < $2 AND next_attempt_at <= CURRENT_TIMESTAMP
 AND NOT EXISTS (SELECT 1 FROM triage_outbox earlier WHERE earlier.flag_id=pending.flag_id
   AND earlier.flag_version < pending.flag_version AND earlier.published_at IS NULL)
 ORDER BY created_at,id FOR UPDATE OF pending SKIP LOCKED LIMIT $1
)
UPDATE triage_outbox o SET attempts=attempts+1,lease_id=$3,
 next_attempt_at=CURRENT_TIMESTAMP+($4 * INTERVAL '1 second')
FROM ready WHERE o.id=ready.id RETURNING o.*
"""


class AlertOutbox:
    def __init__(self, pool: Any, *, lease_seconds: int = 30, max_attempts: int = 5):
        if not 1 <= lease_seconds <= 300 or not 1 <= max_attempts <= 20:
            raise ValueError("Invalid outbox retry/lease bounds")
        self.pool, self.lease_seconds, self.max_attempts = pool, lease_seconds, max_attempts

    async def claim(self, limit: int = 25) -> list[dict]:
        if not 1 <= limit <= 100:
            raise ValueError("Batch size must be 1 to 100")
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "UPDATE triage_outbox SET dead_lettered_at=CURRENT_TIMESTAMP,lease_id=NULL,last_error_class='lease_exhausted' "
                    "WHERE published_at IS NULL AND dead_lettered_at IS NULL AND attempts >= $1 AND next_attempt_at <= CURRENT_TIMESTAMP",
                    self.max_attempts,
                )
                rows = await connection.fetch(
                    _CLAIM, limit, self.max_attempts, uuid4(), self.lease_seconds
                )
        return [dict(row) for row in rows]

    async def complete(self, event: dict) -> bool:
        async with self.pool.acquire() as connection:
            result = await connection.execute(
                "UPDATE triage_outbox SET published_at=CURRENT_TIMESTAMP,lease_id=NULL,last_error_class=NULL "
                "WHERE id=$1 AND lease_id=$2 AND published_at IS NULL AND dead_lettered_at IS NULL",
                event["id"],
                event["lease_id"],
            )
        return result == "UPDATE 1"

    async def fail(self, event: dict) -> None:
        # Fixed error class; transport exception messages can contain secrets.
        async with self.pool.acquire() as connection:
            await connection.execute(
                "UPDATE triage_outbox SET lease_id=NULL,last_error_class='transport_error',"
                "next_attempt_at=CURRENT_TIMESTAMP+($3 * INTERVAL '1 second'),"
                "dead_lettered_at=CASE WHEN attempts >= $4 THEN CURRENT_TIMESTAMP ELSE NULL END "
                "WHERE id=$1 AND lease_id=$2 AND published_at IS NULL AND dead_lettered_at IS NULL",
                event["id"],
                event["lease_id"],
                min(60, 2 ** event["attempts"]),
                self.max_attempts,
            )

    async def replay(self, event_id: UUID) -> bool:
        async with self.pool.acquire() as connection:
            result = await connection.execute(
                "UPDATE triage_outbox SET attempts=0,lease_id=NULL,dead_lettered_at=NULL,last_error_class=NULL,next_attempt_at=CURRENT_TIMESTAMP "
                "WHERE id=$1 AND dead_lettered_at IS NOT NULL AND published_at IS NULL",
                event_id,
            )
        return result == "UPDATE 1"


def encode_event(event: dict) -> bytes:
    payload = event["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    allowed = {
        "flag_id",
        "facility_id",
        "encounter_id",
        "version",
        "state",
        "actor_id",
        "rule_id",
        "rule_version",
        "ruleset_version",
    }
    if not isinstance(payload, dict) or set(payload) != allowed:
        raise ValueError("Alert event metadata schema mismatch")
    return json.dumps(
        {
            "event_id": str(event["id"]),
            "tenant_id": str(event["tenant_id"]),
            "aggregate_id": str(event["flag_id"]),
            "aggregate_type": "triage_flag",
            "event_type": event["event_type"],
            "event_version": 1,
            "occurred_at": event["created_at"].isoformat(),
            "producer": "triage-outbox-publisher",
            "correlation_id": payload["encounter_id"],
            "causation_id": None,
            "data_classification": "restricted",
            "idempotency_key": str(event["id"]),
            "attempt": event["attempts"],
            "artifact_refs": [],
            "payload": payload,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


async def publish_once(
    outbox: AlertOutbox, producer: Any, topic: str, *, batch_size: int = 25
) -> int:
    events = await outbox.claim(batch_size)

    async def deliver(event):
        try:
            await asyncio.wait_for(
                producer.send_and_wait(
                    topic,
                    encode_event(event),
                    key=str(event["flag_id"]).encode(),
                    headers=[("event_type", event["event_type"].encode())],
                ),
                timeout=max(0.5, outbox.lease_seconds / 2),
            )
        except Exception:
            await outbox.fail(event)
            return 0
        return int(await outbox.complete(event))

    return sum(await asyncio.gather(*(deliver(event) for event in events)))


async def _run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("once", "forever", "replay"))
    parser.add_argument("--event-id", type=UUID)
    args = parser.parse_args()
    if not settings.DATABASE_MAINTENANCE_URL:
        raise RuntimeError("DATABASE_MAINTENANCE_URL is required for owned alert outbox access")
    from aiokafka import AIOKafkaProducer

    pool = await asyncpg.create_pool(settings.DATABASE_MAINTENANCE_URL, min_size=1, max_size=4)
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_BROKERS,
        acks="all",
        enable_idempotence=True,
        client_id="medikiosk-triage-outbox",
    )
    outbox = AlertOutbox(pool)
    try:
        if args.command == "replay":
            if args.event_id is None:
                raise ValueError("--event-id is required for replay")
            print(f"Requeued={await outbox.replay(args.event_id)}")
            return
        await producer.start()
        while True:
            count = await publish_once(outbox, producer, settings.TRIAGE_EVENT_TOPIC)
            if count:
                print(f"Published {count} alert event(s)", flush=True)
            if args.command == "once":
                return
            await asyncio.sleep(1)
    finally:
        try:
            await producer.stop()
        finally:
            await pool.close()


if __name__ == "__main__":
    asyncio.run(_run())
