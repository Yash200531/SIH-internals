"""Orchestrate quarantine read, malware scan, promotion, and durable outcome."""

from typing import Any
from uuid import UUID

from app.documents.scanning import MalwareScanner, MalwareScannerError, MalwareScanOutcome
from app.documents.storage import DocumentStore, ObjectVerificationError


class DocumentScanService:
    def __init__(self, repository: Any, store: DocumentStore, scanner: MalwareScanner) -> None:
        self._repository = repository
        self._store = store
        self._scanner = scanner

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
        )
        try:
            payload = await self._store.read_for_scan(started.document)
            result = await self._scanner.scan(payload)
            processing_object_key = None
            if result.outcome is MalwareScanOutcome.CLEAN:
                processing_object_key = await self._store.promote_after_clean_scan(
                    started.document,
                    str(started.run.id),
                )
            await self._repository.complete(
                tenant_id=tenant_id,
                document_id=document_id,
                run_id=started.run.id,
                expected_version=started.document.version,
                result=result,
                processing_object_key=processing_object_key,
            )
        except MalwareScannerError:
            await self._repository.fail(
                tenant_id=tenant_id,
                document_id=document_id,
                run_id=started.run.id,
                expected_version=started.document.version,
                error_class="scanner_error",
            )
        except ObjectVerificationError:
            await self._repository.fail(
                tenant_id=tenant_id,
                document_id=document_id,
                run_id=started.run.id,
                expected_version=started.document.version,
                error_class="source_verification_error",
            )
        except Exception:
            await self._repository.fail(
                tenant_id=tenant_id,
                document_id=document_id,
                run_id=started.run.id,
                expected_version=started.document.version,
                error_class="scan_worker_internal_error",
            )
            raise
