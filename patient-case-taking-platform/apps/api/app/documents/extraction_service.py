"""Fail-closed extraction orchestration across immutable artifact stores."""

from typing import Any, Protocol
from uuid import UUID

from app.documents.extraction import PrescriptionExtractionDraft
from app.documents.extraction_store import (
    ExtractionDraftConflict,
    ExtractionDraftStore,
    ExtractionDraftStoreUnavailable,
)
from app.documents.ocr_artifact import DocumentOcrArtifact
from app.documents.ocr_artifact_store import (
    OcrArtifactStore,
    OcrArtifactStoreUnavailable,
)


class PrescriptionExtractor(Protocol):
    def extract(
        self, artifacts: list[DocumentOcrArtifact]
    ) -> PrescriptionExtractionDraft: ...


class DocumentExtractionService:
    def __init__(
        self,
        repository: Any,
        ocr_store: OcrArtifactStore,
        draft_store: ExtractionDraftStore,
        extractor: PrescriptionExtractor,
    ) -> None:
        self._repository = repository
        self._ocr_store = ocr_store
        self._draft_store = draft_store
        self._extractor = extractor

    async def process(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        expected_version: int,
    ) -> None:
        started = await self._repository.start(
            tenant_id=tenant_id,
            document_id=document_id,
            expected_version=expected_version,
            parser_version="prescription-rules.v1",
        )
        try:
            artifacts: list[DocumentOcrArtifact] = []
            for artifact_id in started.ocr_artifact_ids:
                artifact = await self._ocr_store.get(tenant_id, artifact_id)
                if artifact is None:
                    await self._fail(started, "ocr_artifact_unavailable")
                    return
                artifacts.append(artifact)
            draft = self._extractor.extract(artifacts)
            await self._draft_store.save(draft)
        except OcrArtifactStoreUnavailable:
            await self._fail(started, "ocr_artifact_store_error")
            return
        except (ExtractionDraftConflict, ExtractionDraftStoreUnavailable):
            await self._fail(started, "artifact_store_error")
            return
        except (TypeError, ValueError):
            await self._fail(started, "parser_error")
            return
        except Exception:
            await self._fail(started, "extraction_worker_internal_error")
            raise

        # The immutable MongoDB draft is durable before candidate refs and the
        # processing-completed outbox event commit in PostgreSQL.
        await self._repository.complete(
            tenant_id=tenant_id,
            document_id=document_id,
            run_id=started.run.id,
            expected_version=started.document.version,
            draft=draft,
        )

    async def _fail(self, started: Any, error_class: str) -> None:
        await self._repository.fail(
            tenant_id=started.document.tenant_id,
            document_id=started.document.id,
            run_id=started.run.id,
            expected_version=started.document.version,
            error_class=error_class,
        )
