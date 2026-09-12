"""FastAPI dependencies for the durable document workflow."""

from fastapi import HTTPException

from app.config import settings
from app.database import get_postgres_pool
from app.documents.authorization import (
    DocumentPurposeAuthorizer,
    PostgresDocumentPurposeAuthorizer,
)
from app.documents.operations import PostgresDocumentOperationsRepository
from app.documents.promotion import PostgresReviewedFactRepository
from app.documents.repository import DocumentRepository, PostgresDocumentRepository
from app.documents.review_repository import (
    DocumentReviewRepository,
    PostgresDocumentReviewRepository,
)
from app.documents.storage import DocumentStore, S3DocumentStore


async def get_document_repository() -> DocumentRepository:
    if not settings.DOCUMENT_WORKFLOW_ENABLED:
        raise HTTPException(status_code=503, detail="Document workflow is not enabled")
    return PostgresDocumentRepository(await get_postgres_pool())


async def get_document_purpose_authorizer() -> DocumentPurposeAuthorizer:
    if not settings.DOCUMENT_WORKFLOW_ENABLED:
        raise HTTPException(status_code=503, detail="Document workflow is not enabled")
    return PostgresDocumentPurposeAuthorizer(await get_postgres_pool())


async def get_document_store() -> DocumentStore:
    if not settings.DOCUMENT_WORKFLOW_ENABLED:
        raise HTTPException(status_code=503, detail="Document workflow is not enabled")
    return S3DocumentStore()


async def get_document_review_repository() -> DocumentReviewRepository:
    if not settings.DOCUMENT_WORKFLOW_ENABLED:
        raise HTTPException(status_code=503, detail="Document workflow is not enabled")
    return PostgresDocumentReviewRepository(await get_postgres_pool())


async def get_reviewed_fact_repository() -> PostgresReviewedFactRepository:
    if not settings.DOCUMENT_WORKFLOW_ENABLED:
        raise HTTPException(status_code=503, detail="Document workflow is not enabled")
    return PostgresReviewedFactRepository(await get_postgres_pool())


async def get_document_operations_repository() -> PostgresDocumentOperationsRepository:
    if not settings.DOCUMENT_WORKFLOW_ENABLED:
        raise HTTPException(status_code=503, detail="Document workflow is not enabled")
    return PostgresDocumentOperationsRepository(await get_postgres_pool())
