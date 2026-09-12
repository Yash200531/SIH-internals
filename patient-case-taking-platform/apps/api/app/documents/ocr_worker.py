"""Leased asynchronous OCR worker for normalized document pages."""

import argparse
import asyncio
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import asyncpg
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings
from app.documents.ocr_artifact_store import MongoOcrArtifactStore
from app.documents.ocr_repository import PostgresDocumentOcrRepository
from app.documents.ocr_service import DocumentOcrService
from app.documents.storage import S3DocumentStore
from app.ocr.registry import get_active_provider

_READY_DOCUMENTS = """
SELECT document.tenant_id, document.id, document.version
FROM document_registry AS document
WHERE document.state = 'processing'
  AND EXISTS (
      SELECT 1 FROM document_outbox AS normalized
      WHERE normalized.tenant_id = document.tenant_id
        AND normalized.aggregate_id = document.id
        AND normalized.event_type = 'DocumentPagesNormalized.v1'
  )
  AND NOT EXISTS (
      SELECT 1 FROM document_outbox AS completed
      WHERE completed.tenant_id = document.tenant_id
        AND completed.aggregate_id = document.id
        AND completed.event_type IN ('ai.ocr.completed.v1', 'DocumentOcrDeadLettered.v1')
  )
ORDER BY document.updated_at
LIMIT $1
"""


@dataclass(frozen=True)
class ReadyDocument:
    tenant_id: UUID
    document_id: UUID
    version: int


class OcrQueue(Protocol):
    async def ready(self, *, limit: int) -> list[ReadyDocument]: ...


class OcrProcessor(Protocol):
    async def process(
        self, *, tenant_id: UUID, document_id: UUID, expected_version: int
    ) -> None: ...


class PostgresDocumentOcrQueue:
    """Global queue reader; its pool must use the governed maintenance role."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def ready(self, *, limit: int) -> list[ReadyDocument]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(_READY_DOCUMENTS, limit)
        return [
            ReadyDocument(row["tenant_id"], row["id"], row["version"])
            for row in rows
        ]


async def run_once(
    queue: OcrQueue,
    processor: OcrProcessor,
    *,
    batch_size: int,
    automation_enabled: bool = True,
) -> int:
    if not automation_enabled:
        return 0
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
        except Exception:
            # One expired lease, concurrent replica, or infrastructure failure
            # must not prevent later documents in the batch from progressing.
            continue
    return processed


async def _run() -> None:
    parser = argparse.ArgumentParser(description="Process MediKiosk document OCR")
    parser.add_argument("command", choices=("once", "forever"))
    args = parser.parse_args()
    if not settings.DATABASE_MAINTENANCE_URL:
        raise RuntimeError("DATABASE_MAINTENANCE_URL is required for document OCR")
    provider = get_active_provider()
    warmup = getattr(provider, "warmup", None)
    if warmup is not None:
        # Load/download the configured model before claiming a document. This
        # keeps first-start latency outside the per-page inference timeout and
        # fails the worker visibly if the real provider cannot initialize.
        await warmup()
    pool = await asyncpg.create_pool(settings.DATABASE_MAINTENANCE_URL, min_size=1, max_size=4)
    mongo: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(settings.MONGODB_URL)
    artifact_store = MongoOcrArtifactStore(
        mongo[settings.OCR_ARTIFACT_DATABASE][settings.OCR_ARTIFACT_COLLECTION]
    )
    await artifact_store.ensure_indexes()
    processor = DocumentOcrService(
        PostgresDocumentOcrRepository(
            pool,
            lease_seconds=settings.DOCUMENT_OCR_LEASE_SECONDS,
            max_attempts=settings.DOCUMENT_OCR_MAX_ATTEMPTS,
        ),
        S3DocumentStore(),
        artifact_store,
        provider,
        timeout_seconds=settings.DOCUMENT_OCR_TIMEOUT_SECONDS,
        max_page_bytes=settings.DOCUMENT_OCR_MAX_PAGE_BYTES,
    )
    queue = PostgresDocumentOcrQueue(pool)
    try:
        while True:
            count = await run_once(
                queue,
                processor,
                batch_size=settings.DOCUMENT_OCR_BATCH_SIZE,
                automation_enabled=settings.DOCUMENT_OCR_AUTOMATION_ENABLED,
            )
            print(f"Processed {count} document OCR run(s)")
            if args.command == "once":
                return
            await asyncio.sleep(settings.DOCUMENT_OCR_POLL_INTERVAL_SECONDS)
    finally:
        mongo.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_run())
