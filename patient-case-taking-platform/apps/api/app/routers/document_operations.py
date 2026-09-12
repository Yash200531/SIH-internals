"""Tenant-admin operational status for the document pipeline."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.auth.dependencies import get_current_user
from app.auth.token import TokenPayload
from app.config import settings
from app.documents.dependencies import get_document_operations_repository
from app.documents.operations import PostgresDocumentOperationsRepository

router = APIRouter(prefix="/api/v1/document-operations", tags=["document-operations"])


class DocumentOperationsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    review_backlog: int
    oldest_review_age_seconds: int
    scan_rejected: int
    processing_failed: int
    ocr_dead_letter: int
    extraction_dead_letter: int
    unpublished_events: int
    event_dead_letter: int
    projection_reconciliation_issues: int
    ocr_automation_enabled: bool
    extraction_automation_enabled: bool


@router.get("/status", response_model=DocumentOperationsResponse)
async def document_operations_status(
    user: TokenPayload = Depends(get_current_user),
    repository: PostgresDocumentOperationsRepository = Depends(
        get_document_operations_repository
    ),
) -> DocumentOperationsResponse:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Tenant administrator role required")
    try:
        tenant_id = UUID(user.tenant_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="Invalid authorization scope") from exc
    snapshot = await repository.snapshot(tenant_id)
    return DocumentOperationsResponse(
        **snapshot.__dict__,
        ocr_automation_enabled=settings.DOCUMENT_OCR_AUTOMATION_ENABLED,
        extraction_automation_enabled=settings.DOCUMENT_EXTRACTION_AUTOMATION_ENABLED,
    )
