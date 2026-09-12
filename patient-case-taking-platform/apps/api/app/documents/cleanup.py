"""Maintenance worker for expiring abandoned direct-upload sessions."""

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from app.config import settings

_EXPIRE_ABANDONED = """
WITH expired AS (
    SELECT id
    FROM document_registry
    WHERE state = 'initiated' AND upload_expires_at <= $1
    ORDER BY upload_expires_at
    FOR UPDATE SKIP LOCKED
    LIMIT $2
)
UPDATE document_registry AS document
SET state = 'cancelled', version = document.version + 1, updated_at = $1
FROM expired
WHERE document.id = expired.id
RETURNING document.id, document.tenant_id, document.version
"""

_INSERT_EXPIRY_EVENT = """
INSERT INTO document_outbox (
    event_id, tenant_id, aggregate_id, event_type, event_version, producer,
    correlation_id, data_classification, idempotency_key, artifact_refs, payload
) VALUES ($1, $2, $3, 'DocumentUploadExpired.v1', 1, 'document-upload-cleanup',
          $3, 'restricted', $4, '[]'::JSONB, $5)
ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
"""


@dataclass(frozen=True)
class ExpiredUpload:
    document_id: UUID
    tenant_id: UUID
    version: int


class PostgresAbandonedUploadCleaner:
    """Global maintenance adapter; its pool must use a governed BYPASSRLS role."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def expire(self, *, now: datetime, limit: int) -> list[ExpiredUpload]:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                rows = await connection.fetch(_EXPIRE_ABANDONED, now, limit)
                expired = [
                    ExpiredUpload(
                        document_id=row["id"],
                        tenant_id=row["tenant_id"],
                        version=row["version"],
                    )
                    for row in rows
                ]
                for item in expired:
                    await connection.execute(
                        _INSERT_EXPIRY_EVENT,
                        uuid4(),
                        item.tenant_id,
                        item.document_id,
                        f"{item.document_id}:upload-expired:{item.version}",
                        json.dumps({"state": "cancelled", "document_version": item.version}),
                    )
                return expired


async def run_once(pool: Any, *, now: datetime | None = None) -> int:
    cleaner = PostgresAbandonedUploadCleaner(pool)
    expired = await cleaner.expire(
        now=now or datetime.now(UTC),
        limit=settings.DOCUMENT_UPLOAD_CLEANUP_BATCH_SIZE,
    )
    return len(expired)


async def _run() -> None:
    parser = argparse.ArgumentParser(description="Expire abandoned MediKiosk uploads")
    parser.add_argument("command", choices=("once", "forever"))
    args = parser.parse_args()
    if not settings.DATABASE_MAINTENANCE_URL:
        raise RuntimeError("DATABASE_MAINTENANCE_URL is required for upload cleanup")
    pool = await asyncpg.create_pool(settings.DATABASE_MAINTENANCE_URL, min_size=1, max_size=2)
    try:
        while True:
            count = await run_once(pool)
            print(f"Expired {count} abandoned upload(s)")
            if args.command == "once":
                return
            await asyncio.sleep(settings.DOCUMENT_UPLOAD_CLEANUP_INTERVAL_SECONDS)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_run())
