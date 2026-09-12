"""Fail-closed orchestration for normalized document page artifacts."""

import asyncio
from typing import Any, Protocol
from uuid import UUID

from app.documents.normalization import DocumentNormalizationError, NormalizedPage
from app.documents.storage import DocumentStore, ObjectVerificationError


class PageNormalizer(Protocol):
    def normalize(self, payload: bytes, mime: str) -> list[NormalizedPage]: ...


class DocumentNormalizationService:
    def __init__(
        self,
        repository: Any,
        store: DocumentStore,
        normalizer: PageNormalizer,
        *,
        timeout_seconds: float = 30,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Normalization timeout must be positive")
        self._repository = repository
        self._store = store
        self._normalizer = normalizer
        self._timeout_seconds = timeout_seconds

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
            preprocessing_version="normalize.v1",
        )
        try:
            mime = started.document.detected_mime
            if mime is None:
                raise ObjectVerificationError("Detected document type is unavailable")
            payload = await self._store.read_processing_source(started.document)
            pages = await asyncio.wait_for(
                asyncio.to_thread(self._normalizer.normalize, payload, mime),
                timeout=self._timeout_seconds,
            )
            stored_pages = await self._store.store_normalized_pages(
                started.document,
                str(started.run.id),
                pages,
            )
            await self._repository.complete(
                tenant_id=tenant_id,
                document_id=document_id,
                run_id=started.run.id,
                expected_version=started.document.version,
                pages=stored_pages,
            )
        except DocumentNormalizationError:
            await self._fail(started, "normalization_rejected")
        except ObjectVerificationError:
            await self._fail(started, "source_verification_error")
        except TimeoutError:
            await self._fail(started, "normalization_timeout")
        except Exception:
            await self._fail(started, "normalization_worker_internal_error")
            raise

    async def _fail(self, started: Any, error_class: str) -> None:
        await self._repository.fail(
            tenant_id=started.document.tenant_id,
            document_id=started.document.id,
            run_id=started.run.id,
            expected_version=started.document.version,
            error_class=error_class,
        )
