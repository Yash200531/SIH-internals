"""Extraction orchestration durability and fail-closed behavior tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.documents.extraction import PrescriptionExtractionDraft, PrescriptionRulesExtractor
from app.documents.extraction_repository import (
    DocumentExtractionRun,
    ExtractionStartResult,
)
from app.documents.extraction_service import DocumentExtractionService
from app.documents.extraction_store import ExtractionDraftStoreUnavailable
from app.documents.ocr_artifact import DocumentOcrArtifact
from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.ocr.base import OCRRegion, OCRResult


def _source() -> tuple[ExtractionStartResult, DocumentOcrArtifact]:
    document = DocumentRegistryEntry(
        tenant_id=uuid4(),
        facility_id=uuid4(),
        patient_id=uuid4(),
        encounter_id=uuid4(),
        uploader_actor_id=uuid4(),
        purpose="treatment",
        consent_reference=str(uuid4()),
        original_filename="synthetic.png",
        declared_document_class="prescription",
        declared_mime="image/png",
        declared_size_bytes=16,
        idempotency_key="extraction-service-test",
        state=DocumentState.PROCESSING,
        version=10,
        source_checksum_sha256="a" * 64,
        active_ocr_run_id=uuid4(),
    )
    artifact = DocumentOcrArtifact.from_result(
        tenant_id=document.tenant_id,
        document_id=document.id,
        page_artifact_id=uuid4(),
        ocr_run_id=document.active_ocr_run_id,
        page_number=1,
        width=300,
        height=100,
        source_checksum_sha256="a" * 64,
        page_checksum_sha256="b" * 64,
        preprocessing_version="normalize.v1",
        result=OCRResult(
            text="Tab Metformin 500 mg",
            regions=[
                OCRRegion(
                    text="Tab Metformin 500 mg",
                    confidence=0.9,
                    bbox=(1, 2, 250, 30),
                )
            ],
            confidence=0.9,
            provider="fixture",
            model_version="fixture-v1",
            language_pack_version="fixture-en-v1",
            duration_ms=1,
        ),
    )
    now = datetime.now(UTC)
    run = DocumentExtractionRun(
        id=uuid4(),
        tenant_id=document.tenant_id,
        document_id=document.id,
        ocr_run_id=document.active_ocr_run_id,
        attempt=1,
        parser_version="prescription-rules.v1",
        schema_version="DocumentExtractionDraft.v1",
        status="running",
        started_at=now,
        lease_expires_at=now + timedelta(minutes=1),
    )
    return ExtractionStartResult(document, run, [artifact.artifact_id]), artifact


class _Repository:
    def __init__(
        self,
        started: ExtractionStartResult,
        complete_error: Exception | None = None,
    ) -> None:
        self.started = started
        self.complete_error = complete_error
        self.completed: dict[str, object] | None = None
        self.failed: dict[str, object] | None = None

    async def start(self, **_values: object) -> ExtractionStartResult:
        return self.started

    async def complete(self, **values: object) -> DocumentRegistryEntry:
        if self.complete_error is not None:
            raise self.complete_error
        self.completed = values
        return self.started.document

    async def fail(self, **values: object) -> DocumentRegistryEntry:
        self.failed = values
        return self.started.document


class _OcrStore:
    def __init__(self, artifact: DocumentOcrArtifact | None) -> None:
        self.artifact = artifact

    async def get(self, _tenant_id, _artifact_id) -> DocumentOcrArtifact | None:
        return self.artifact


class _DraftStore:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.saved: PrescriptionExtractionDraft | None = None

    async def save(self, draft: PrescriptionExtractionDraft) -> bool:
        if self.error is not None:
            raise self.error
        self.saved = draft
        return True


class _BrokenExtractor:
    def extract(self, _artifacts) -> PrescriptionExtractionDraft:
        raise ValueError("raw parser detail")


@pytest.mark.asyncio
async def test_draft_is_saved_before_postgres_completion() -> None:
    started, artifact = _source()
    repository = _Repository(started)
    draft_store = _DraftStore()
    service = DocumentExtractionService(
        repository,
        _OcrStore(artifact),
        draft_store,
        PrescriptionRulesExtractor(),
    )

    await service.process(
        tenant_id=started.document.tenant_id,
        document_id=started.document.id,
        expected_version=9,
    )

    assert draft_store.saved is not None
    assert repository.completed is not None
    assert repository.completed["draft"] == draft_store.saved
    assert repository.failed is None


@pytest.mark.asyncio
async def test_missing_ocr_artifact_is_persisted_as_safe_retry() -> None:
    started, _artifact = _source()
    repository = _Repository(started)
    service = DocumentExtractionService(
        repository,
        _OcrStore(None),
        _DraftStore(),
        PrescriptionRulesExtractor(),
    )

    await service.process(
        tenant_id=started.document.tenant_id,
        document_id=started.document.id,
        expected_version=9,
    )

    assert repository.failed is not None
    assert repository.failed["error_class"] == "ocr_artifact_unavailable"


@pytest.mark.asyncio
async def test_parser_failure_is_persisted_without_raw_detail() -> None:
    started, artifact = _source()
    repository = _Repository(started)
    service = DocumentExtractionService(
        repository,
        _OcrStore(artifact),
        _DraftStore(),
        _BrokenExtractor(),
    )

    await service.process(
        tenant_id=started.document.tenant_id,
        document_id=started.document.id,
        expected_version=9,
    )

    assert repository.failed is not None
    assert repository.failed["error_class"] == "parser_error"
    assert "raw parser detail" not in str(repository.failed)


@pytest.mark.asyncio
async def test_draft_store_failure_is_retryable() -> None:
    started, artifact = _source()
    repository = _Repository(started)
    service = DocumentExtractionService(
        repository,
        _OcrStore(artifact),
        _DraftStore(ExtractionDraftStoreUnavailable("raw mongo detail")),
        PrescriptionRulesExtractor(),
    )

    await service.process(
        tenant_id=started.document.tenant_id,
        document_id=started.document.id,
        expected_version=9,
    )

    assert repository.failed is not None
    assert repository.failed["error_class"] == "artifact_store_error"


@pytest.mark.asyncio
async def test_postgres_completion_failure_leaves_run_reclaimable() -> None:
    started, artifact = _source()
    repository = _Repository(started, complete_error=RuntimeError("postgres unavailable"))
    service = DocumentExtractionService(
        repository,
        _OcrStore(artifact),
        _DraftStore(),
        PrescriptionRulesExtractor(),
    )

    with pytest.raises(RuntimeError, match="postgres unavailable"):
        await service.process(
            tenant_id=started.document.tenant_id,
            document_id=started.document.id,
            expected_version=9,
        )

    assert repository.failed is None
