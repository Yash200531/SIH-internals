"""Idempotent, tenant-scoped MongoDB OCR artifact persistence tests."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.documents.ocr_artifact import DocumentOcrArtifact
from app.documents.ocr_artifact_store import MongoOcrArtifactStore, OcrArtifactConflict
from app.ocr.base import OCRRegion, OCRResult


class _Collection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, object]] = {}
        self.indexes: list[tuple[object, dict[str, object]]] = []

    async def create_index(self, keys: object, **options: object) -> None:
        self.indexes.append((keys, options))

    async def update_one(
        self,
        query: dict[str, object],
        update: dict[str, dict[str, object]],
        *,
        upsert: bool,
    ) -> SimpleNamespace:
        identity = str(query["_id"])
        if identity in self.documents:
            return SimpleNamespace(upserted_id=None)
        assert upsert is True
        self.documents[identity] = dict(update["$setOnInsert"])
        return SimpleNamespace(upserted_id=identity)

    async def find_one(self, query: dict[str, object]) -> dict[str, object] | None:
        value = self.documents.get(str(query["_id"]))
        if value is None or value["tenant_id"] != query["tenant_id"]:
            return None
        return dict(value)


def _artifact() -> DocumentOcrArtifact:
    return DocumentOcrArtifact.from_result(
        tenant_id=uuid4(),
        document_id=uuid4(),
        page_artifact_id=uuid4(),
        ocr_run_id=uuid4(),
        page_number=1,
        width=100,
        height=40,
        source_checksum_sha256="a" * 64,
        page_checksum_sha256="b" * 64,
        preprocessing_version="normalize.v1",
        result=OCRResult(
            text="Rx Metformin 500 mg",
            regions=[
                OCRRegion(
                    text="Rx Metformin 500 mg",
                    confidence=0.9,
                    bbox=(1, 2, 90, 20),
                )
            ],
            confidence=0.9,
            provider="mock",
            model_version="mock-ocr-v1",
            language_pack_version="synthetic-en-v1",
            duration_ms=4,
        ),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_save_is_idempotent_and_never_overwrites_artifact_content() -> None:
    collection = _Collection()
    store = MongoOcrArtifactStore(collection)
    artifact = _artifact()

    assert await store.save(artifact) is True
    assert await store.save(artifact) is False

    changed = artifact.model_copy(update={"normalized_text": "different"})
    with pytest.raises(OcrArtifactConflict):
        await store.save(changed)


@pytest.mark.asyncio
async def test_get_is_tenant_scoped() -> None:
    store = MongoOcrArtifactStore(_Collection())
    artifact = _artifact()
    await store.save(artifact)

    assert await store.get(artifact.tenant_id, artifact.artifact_id) == artifact
    assert await store.get(uuid4(), artifact.artifact_id) is None


@pytest.mark.asyncio
async def test_store_creates_idempotency_and_document_lookup_indexes() -> None:
    collection = _Collection()
    store = MongoOcrArtifactStore(collection)

    await store.ensure_indexes()

    assert len(collection.indexes) == 2
    assert any(options.get("unique") is True for _keys, options in collection.indexes)
