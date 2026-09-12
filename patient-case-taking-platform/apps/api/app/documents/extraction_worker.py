"""Leased asynchronous prescription extraction worker."""

import argparse
import asyncio
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import asyncpg
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings
from app.documents.extraction import PrescriptionRulesExtractor
from app.documents.extraction_repository import (
    PostgresDocumentExtractionRepository,
)
from app.documents.extraction_service import DocumentExtractionService
from app.documents.extraction_store import MongoExtractionDraftStore
from app.documents.ocr_artifact_store import MongoOcrArtifactStore

_READY_DOCUMENTS = """
SELECT document.tenant_id, document.id, document.version
FROM document_registry AS document
WHERE document.state = 'processing'
  AND document.declared_document_class = 'prescription'
  AND EXISTS (
      SELECT 1 FROM document_outbox AS ocr
      WHERE ocr.tenant_id = document.tenant_id
        AND ocr.aggregate_id = document.id
        AND ocr.event_type = 'ai.ocr.completed.v1'
  )
  AND NOT EXISTS (
      SELECT 1 FROM document_outbox AS completed
      WHERE completed.tenant_id = document.tenant_id
        AND completed.aggregate_id = document.id
        AND completed.event_type IN (
            'DocumentProcessingCompleted.v1',
            'DocumentExtractionDeadLettered.v1'
        )
  )
ORDER BY document.updated_at
LIMIT $1
"""


@dataclass(frozen=True)
class ReadyDocument:
    tenant_id: UUID
    document_id: UUID
    version: int


class ExtractionQueue(Protocol):
    async def ready(self, *, limit: int) -> list[ReadyDocument]: ...


class ExtractionProcessor(Protocol):
    async def process(
        self, *, tenant_id: UUID, document_id: UUID, expected_version: int
    ) -> None: ...


class PostgresDocumentExtractionQueue:
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
    queue: ExtractionQueue,
    processor: ExtractionProcessor,
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
            continue
    return processed


async def _run() -> None:
    parser = argparse.ArgumentParser(description="Extract MediKiosk prescription drafts")
    parser.add_argument("command", choices=("once", "forever"))
    args = parser.parse_args()
    if not settings.DATABASE_MAINTENANCE_URL:
        raise RuntimeError("DATABASE_MAINTENANCE_URL is required for extraction")
    pool = await asyncpg.create_pool(settings.DATABASE_MAINTENANCE_URL, min_size=1, max_size=4)
    mongo: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(settings.MONGODB_URL)
    database = mongo[settings.OCR_ARTIFACT_DATABASE]
    ocr_store = MongoOcrArtifactStore(database[settings.OCR_ARTIFACT_COLLECTION])
    draft_store = MongoExtractionDraftStore(
        database[settings.EXTRACTION_DRAFT_COLLECTION]
    )
    await draft_store.ensure_indexes()
    processor = DocumentExtractionService(
        PostgresDocumentExtractionRepository(
            pool,
            lease_seconds=settings.DOCUMENT_EXTRACTION_LEASE_SECONDS,
            max_attempts=settings.DOCUMENT_EXTRACTION_MAX_ATTEMPTS,
        ),
        ocr_store,
        draft_store,
        PrescriptionRulesExtractor(),
    )
    queue = PostgresDocumentExtractionQueue(pool)
    try:
        while True:
            count = await run_once(
                queue,
                processor,
                batch_size=settings.DOCUMENT_EXTRACTION_BATCH_SIZE,
                automation_enabled=settings.DOCUMENT_EXTRACTION_AUTOMATION_ENABLED,
            )
            print(f"Processed {count} document extraction run(s)")
            if args.command == "once":
                return
            await asyncio.sleep(settings.DOCUMENT_EXTRACTION_POLL_INTERVAL_SECONDS)
    finally:
        mongo.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_run())
