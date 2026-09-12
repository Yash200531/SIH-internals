"""Fail-closed OCR orchestration across page, MongoDB, and PostgreSQL stores."""

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.documents.ocr_artifact import DocumentOcrArtifact
from app.documents.ocr_artifact_store import (
    OcrArtifactConflict,
    OcrArtifactStore,
    OcrArtifactStoreUnavailable,
)
from app.documents.storage import DocumentStore, ObjectVerificationError
from app.ocr.base import OCRProvider, OCRResult


class OcrProviderExecutionError(RuntimeError):
    """Sanitized provider-boundary error used for retry classification."""


class DocumentOcrService:
    def __init__(
        self,
        repository: Any,
        document_store: DocumentStore,
        artifact_store: OcrArtifactStore,
        provider: OCRProvider,
        *,
        timeout_seconds: float = 60,
        max_page_bytes: int = 50 * 1024 * 1024,
    ) -> None:
        if timeout_seconds <= 0 or max_page_bytes <= 0:
            raise ValueError("OCR timeout and page byte limit must be positive")
        self._repository = repository
        self._document_store = document_store
        self._artifact_store = artifact_store
        self._provider = provider
        self._timeout_seconds = timeout_seconds
        self._max_page_bytes = max_page_bytes

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
            provider=self._provider.provider_name,
            model_version=self._provider.model_version,
            language_pack_version=self._provider.language_pack_version,
        )
        try:
            source_checksum = started.document.source_checksum_sha256
            if source_checksum is None:
                raise ObjectVerificationError("Document source checksum is unavailable")
            artifacts: list[DocumentOcrArtifact] = []
            created_at = datetime.now(UTC)
            for page in started.pages:
                payload = await self._document_store.read_normalized_page(
                    started.document,
                    page,
                    max_bytes=self._max_page_bytes,
                )
                result = await self._recognize(payload, page.mime)
                artifacts.append(
                    DocumentOcrArtifact.from_result(
                        tenant_id=tenant_id,
                        document_id=document_id,
                        page_artifact_id=page.id,
                        ocr_run_id=started.run.id,
                        page_number=page.page_number,
                        width=page.width,
                        height=page.height,
                        source_checksum_sha256=source_checksum,
                        page_checksum_sha256=page.checksum_sha256,
                        preprocessing_version=page.preprocessing_version,
                        result=result,
                        created_at=created_at,
                    )
                )
            for artifact in artifacts:
                await self._artifact_store.save(artifact)
        except ObjectVerificationError:
            await self._fail(started, "page_verification_error")
            return
        except TimeoutError:
            await self._fail(started, "provider_timeout")
            return
        except OcrProviderExecutionError:
            await self._fail(started, "provider_error")
            return
        except ValidationError:
            await self._fail(started, "artifact_validation_error")
            return
        except (OcrArtifactConflict, OcrArtifactStoreUnavailable):
            await self._fail(started, "artifact_store_error")
            return
        except Exception:
            await self._fail(started, "ocr_worker_internal_error")
            raise

        # MongoDB artifacts are durable before the transactional refs/outbox commit.
        # If this boundary fails, leave the leased run reclaimable with the same IDs.
        await self._repository.complete(
            tenant_id=tenant_id,
            document_id=document_id,
            run_id=started.run.id,
            expected_version=started.document.version,
            artifacts=artifacts,
        )

    async def _recognize(self, payload: bytes, mime: str) -> OCRResult:
        try:
            return await asyncio.wait_for(
                self._provider.recognize(payload, mime),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            raise
        except Exception as exc:
            raise OcrProviderExecutionError("OCR provider failed") from exc

    async def _fail(self, started: Any, error_class: str) -> None:
        await self._repository.fail(
            tenant_id=started.document.tenant_id,
            document_id=started.document.id,
            run_id=started.run.id,
            expected_version=started.document.version,
            error_class=error_class,
        )
