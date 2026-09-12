"""Asynchronous scanner worker driven by durable uploaded-document events."""

import argparse
import asyncio
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import asyncpg

from app.config import settings
from app.documents.scan_repository import PostgresDocumentScanRepository
from app.documents.scan_service import DocumentScanService
from app.documents.scanning import ClamAVScanner
from app.documents.storage import S3DocumentStore

_READY_DOCUMENTS = """
SELECT document.tenant_id, document.id, document.version
FROM document_registry AS document
WHERE document.state = 'quarantined'
  AND EXISTS (
      SELECT 1
      FROM document_outbox AS event
      WHERE event.tenant_id = document.tenant_id
        AND event.aggregate_id = document.id
        AND event.event_type = 'DocumentUploaded.v1'
  )
ORDER BY document.updated_at
LIMIT $1
"""


@dataclass(frozen=True)
class ReadyDocument:
    tenant_id: UUID
    document_id: UUID
    version: int


class ScanQueue(Protocol):
    async def ready(self, *, limit: int) -> list[ReadyDocument]: ...


class ScanProcessor(Protocol):
    async def process(
        self, *, tenant_id: UUID, document_id: UUID, expected_version: int
    ) -> None: ...


class PostgresDocumentScanQueue:
    """Global queue reader; its pool must use the governed maintenance role."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def ready(self, *, limit: int) -> list[ReadyDocument]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(_READY_DOCUMENTS, limit)
        return [
            ReadyDocument(
                tenant_id=row["tenant_id"],
                document_id=row["id"],
                version=row["version"],
            )
            for row in rows
        ]


async def run_once(queue: ScanQueue, processor: ScanProcessor) -> int:
    ready = await queue.ready(limit=settings.DOCUMENT_SCAN_BATCH_SIZE)
    processed = 0
    for document in ready:
        try:
            await processor.process(
                tenant_id=document.tenant_id,
                document_id=document.document_id,
                expected_version=document.version,
            )
            processed += 1
        except (ValueError, RuntimeError):
            # State/version conflicts are expected when another replica wins.
            # The processor already persists safe failures after a run starts.
            continue
    return processed


async def _run() -> None:
    parser = argparse.ArgumentParser(description="Process MediKiosk document scans")
    parser.add_argument("command", choices=("once", "forever"))
    args = parser.parse_args()
    if not settings.DATABASE_MAINTENANCE_URL:
        raise RuntimeError("DATABASE_MAINTENANCE_URL is required for document scanning")
    pool = await asyncpg.create_pool(settings.DATABASE_MAINTENANCE_URL, min_size=1, max_size=4)
    scanner = ClamAVScanner(
        host=settings.CLAMAV_HOST,
        port=settings.CLAMAV_PORT,
        timeout_seconds=settings.CLAMAV_TIMEOUT_SECONDS,
        max_bytes=settings.DOCUMENT_SCAN_MAX_BYTES,
    )
    processor = DocumentScanService(
        PostgresDocumentScanRepository(pool),
        S3DocumentStore(),
        scanner,
    )
    queue = PostgresDocumentScanQueue(pool)
    try:
        while True:
            count = await run_once(queue, processor)
            print(f"Processed {count} document scan(s)")
            if args.command == "once":
                return
            await asyncio.sleep(settings.DOCUMENT_SCAN_POLL_INTERVAL_SECONDS)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_run())
