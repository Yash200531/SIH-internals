"""Asynchronous worker for bounded page normalization."""

import argparse
import asyncio
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import asyncpg

from app.config import settings
from app.documents.normalization import DocumentNormalizer
from app.documents.normalization_repository import (
    PostgresDocumentNormalizationRepository,
)
from app.documents.normalization_service import DocumentNormalizationService
from app.documents.storage import S3DocumentStore

_READY_DOCUMENTS = """
SELECT document.tenant_id, document.id, document.version
FROM document_registry AS document
WHERE document.state = 'scan_passed'
  AND EXISTS (
      SELECT 1
      FROM document_outbox AS event
      WHERE event.tenant_id = document.tenant_id
        AND event.aggregate_id = document.id
        AND event.event_type = 'DocumentScanCompleted.v1'
        AND event.payload ->> 'outcome' = 'clean'
  )
ORDER BY document.updated_at
LIMIT $1
"""


@dataclass(frozen=True)
class ReadyDocument:
    tenant_id: UUID
    document_id: UUID
    version: int


class NormalizationQueue(Protocol):
    async def ready(self, *, limit: int) -> list[ReadyDocument]: ...


class NormalizationProcessor(Protocol):
    async def process(
        self, *, tenant_id: UUID, document_id: UUID, expected_version: int
    ) -> None: ...


class PostgresDocumentNormalizationQueue:
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


async def run_once(
    queue: NormalizationQueue,
    processor: NormalizationProcessor,
    *,
    batch_size: int,
) -> int:
    ready = await queue.ready(limit=batch_size)
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
            # The service persists safe failures after a run starts.
            continue
    return processed


async def _run() -> None:
    parser = argparse.ArgumentParser(description="Normalize MediKiosk document pages")
    parser.add_argument("command", choices=("once", "forever"))
    args = parser.parse_args()
    if not settings.DATABASE_MAINTENANCE_URL:
        raise RuntimeError("DATABASE_MAINTENANCE_URL is required for page normalization")
    pool = await asyncpg.create_pool(settings.DATABASE_MAINTENANCE_URL, min_size=1, max_size=4)
    normalizer = DocumentNormalizer(
        max_pages=settings.DOCUMENT_NORMALIZATION_MAX_PAGES,
        max_pixels_per_page=settings.DOCUMENT_NORMALIZATION_MAX_PIXELS_PER_PAGE,
        max_total_pixels=settings.DOCUMENT_NORMALIZATION_MAX_TOTAL_PIXELS,
        render_dpi=settings.DOCUMENT_NORMALIZATION_RENDER_DPI,
    )
    processor = DocumentNormalizationService(
        PostgresDocumentNormalizationRepository(pool),
        S3DocumentStore(),
        normalizer,
        timeout_seconds=settings.DOCUMENT_NORMALIZATION_TIMEOUT_SECONDS,
    )
    queue = PostgresDocumentNormalizationQueue(pool)
    try:
        while True:
            count = await run_once(
                queue,
                processor,
                batch_size=settings.DOCUMENT_NORMALIZATION_BATCH_SIZE,
            )
            print(f"Processed {count} document normalization run(s)")
            if args.command == "once":
                return
            await asyncio.sleep(settings.DOCUMENT_NORMALIZATION_POLL_INTERVAL_SECONDS)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_run())
