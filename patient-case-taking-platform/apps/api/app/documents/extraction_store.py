"""Tenant-scoped immutable prescription extraction draft persistence."""

from typing import Any, Protocol
from uuid import UUID

from pymongo.errors import PyMongoError

from app.documents.extraction import PrescriptionExtractionDraft


class ExtractionDraftConflict(RuntimeError):
    """Raised when a deterministic draft identity maps to different content."""


class ExtractionDraftStoreUnavailable(RuntimeError):
    """Raised without persistence details when the extraction store fails."""


class ExtractionDraftStore(Protocol):
    async def save(self, draft: PrescriptionExtractionDraft) -> bool: ...

    async def get(
        self, tenant_id: UUID, draft_id: UUID
    ) -> PrescriptionExtractionDraft | None: ...


def _canonical(draft: PrescriptionExtractionDraft) -> dict[str, object]:
    return draft.model_dump(mode="json", exclude={"created_at"})


class MongoExtractionDraftStore:
    """Immutable MongoDB store for deterministic extraction drafts."""

    def __init__(self, collection: Any) -> None:
        self._collection = collection

    async def ensure_indexes(self) -> None:
        try:
            await self._collection.create_index(
                [("tenant_id", 1), ("ocr_run_id", 1), ("parser_version", 1)],
                name="extraction_draft_run_parser_unique",
                unique=True,
            )
            await self._collection.create_index(
                [("tenant_id", 1), ("document_id", 1)],
                name="extraction_draft_document",
            )
        except PyMongoError as exc:
            raise ExtractionDraftStoreUnavailable(
                "Extraction draft store is unavailable"
            ) from exc

    async def save(self, draft: PrescriptionExtractionDraft) -> bool:
        document = draft.model_dump(mode="json")
        document["_id"] = str(draft.draft_id)
        try:
            result = await self._collection.update_one(
                {"_id": str(draft.draft_id)},
                {"$setOnInsert": document},
                upsert=True,
            )
        except PyMongoError as exc:
            raise ExtractionDraftStoreUnavailable(
                "Extraction draft store is unavailable"
            ) from exc
        stored = await self.get(draft.tenant_id, draft.draft_id)
        if stored is None or _canonical(stored) != _canonical(draft):
            raise ExtractionDraftConflict(
                "Extraction draft identity conflicts with stored content"
            )
        return result.upserted_id is not None

    async def get(
        self, tenant_id: UUID, draft_id: UUID
    ) -> PrescriptionExtractionDraft | None:
        try:
            document = await self._collection.find_one(
                {"_id": str(draft_id), "tenant_id": str(tenant_id)}
            )
        except PyMongoError as exc:
            raise ExtractionDraftStoreUnavailable(
                "Extraction draft store is unavailable"
            ) from exc
        if document is None:
            return None
        return PrescriptionExtractionDraft.model_validate(document)
