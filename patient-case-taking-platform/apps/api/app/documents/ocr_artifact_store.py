"""Tenant-scoped immutable OCR artifact persistence."""

from typing import Any, Protocol
from uuid import UUID

from pymongo.errors import PyMongoError

from app.documents.ocr_artifact import DocumentOcrArtifact


class OcrArtifactConflict(RuntimeError):
    """Raised when a deterministic artifact identity maps to different content."""


class OcrArtifactStoreUnavailable(RuntimeError):
    """Raised without persistence-layer details when the artifact store fails."""


class OcrArtifactStore(Protocol):
    async def save(self, artifact: DocumentOcrArtifact) -> bool: ...

    async def get(
        self, tenant_id: UUID, artifact_id: UUID
    ) -> DocumentOcrArtifact | None: ...


def _canonical(artifact: DocumentOcrArtifact) -> dict[str, object]:
    return artifact.model_dump(mode="json", exclude={"created_at"})


class MongoOcrArtifactStore:
    """Immutable MongoDB store; deterministic IDs make retries idempotent."""

    def __init__(self, collection: Any) -> None:
        self._collection = collection

    async def ensure_indexes(self) -> None:
        try:
            await self._collection.create_index(
                [("tenant_id", 1), ("ocr_run_id", 1), ("page_artifact_id", 1)],
                name="ocr_artifact_run_page_unique",
                unique=True,
            )
            await self._collection.create_index(
                [("tenant_id", 1), ("document_id", 1), ("page_number", 1)],
                name="ocr_artifact_document_pages",
            )
        except PyMongoError as exc:
            raise OcrArtifactStoreUnavailable("OCR artifact store is unavailable") from exc

    async def save(self, artifact: DocumentOcrArtifact) -> bool:
        document = artifact.model_dump(mode="json")
        document["_id"] = str(artifact.artifact_id)
        try:
            result = await self._collection.update_one(
                {"_id": str(artifact.artifact_id)},
                {"$setOnInsert": document},
                upsert=True,
            )
        except PyMongoError as exc:
            raise OcrArtifactStoreUnavailable("OCR artifact store is unavailable") from exc
        stored = await self.get(artifact.tenant_id, artifact.artifact_id)
        if stored is None or _canonical(stored) != _canonical(artifact):
            raise OcrArtifactConflict("OCR artifact identity conflicts with stored content")
        return result.upserted_id is not None

    async def get(
        self, tenant_id: UUID, artifact_id: UUID
    ) -> DocumentOcrArtifact | None:
        try:
            document = await self._collection.find_one(
                {"_id": str(artifact_id), "tenant_id": str(tenant_id)}
            )
        except PyMongoError as exc:
            raise OcrArtifactStoreUnavailable("OCR artifact store is unavailable") from exc
        if document is None:
            return None
        return DocumentOcrArtifact.model_validate(document)
