"""Immutable MongoDB extraction-draft persistence tests."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.documents.extraction import PrescriptionRulesExtractor
from app.documents.extraction_store import (
    ExtractionDraftConflict,
    MongoExtractionDraftStore,
)
from app.documents.ocr_artifact import DocumentOcrArtifact
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


def _draft():
    artifact = DocumentOcrArtifact.from_result(
        tenant_id=uuid4(),
        document_id=uuid4(),
        page_artifact_id=uuid4(),
        ocr_run_id=uuid4(),
        page_number=1,
        width=200,
        height=80,
        source_checksum_sha256="a" * 64,
        page_checksum_sha256="b" * 64,
        preprocessing_version="normalize.v1",
        result=OCRResult(
            text="Tab Metformin 500 mg",
            regions=[
                OCRRegion(
                    text="Tab Metformin 500 mg",
                    confidence=0.9,
                    bbox=(1, 2, 190, 30),
                )
            ],
            confidence=0.9,
            provider="fixture",
            model_version="fixture-v1",
            language_pack_version="fixture-en-v1",
            duration_ms=1,
        ),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return PrescriptionRulesExtractor().extract([artifact])


@pytest.mark.asyncio
async def test_draft_save_is_idempotent_and_immutable() -> None:
    store = MongoExtractionDraftStore(_Collection())
    draft = _draft()

    assert await store.save(draft) is True
    assert await store.save(draft) is False
    with pytest.raises(ExtractionDraftConflict):
        await store.save(draft.model_copy(update={"warnings": ("different",)}))


@pytest.mark.asyncio
async def test_draft_get_is_tenant_scoped() -> None:
    store = MongoExtractionDraftStore(_Collection())
    draft = _draft()
    await store.save(draft)

    assert await store.get(draft.tenant_id, draft.draft_id) == draft
    assert await store.get(uuid4(), draft.draft_id) is None


@pytest.mark.asyncio
async def test_draft_store_creates_run_and_document_indexes() -> None:
    collection = _Collection()
    store = MongoExtractionDraftStore(collection)

    await store.ensure_indexes()

    assert len(collection.indexes) == 2
    assert any(options.get("unique") is True for _keys, options in collection.indexes)
