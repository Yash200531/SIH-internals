"""Authorized document-registry endpoints."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response

from app.audit.emitter import audit_emitter
from app.auth.dependencies import get_current_user
from app.auth.token import TokenPayload
from app.config import settings
from app.documents.authorization import ConsentAuthorizationDenied, DocumentPurposeAuthorizer
from app.documents.dependencies import (
    get_document_purpose_authorizer,
    get_document_repository,
    get_document_store,
)
from app.documents.registry import (
    ConcurrentDocumentUpdate,
    DocumentRegistryEntry,
    InvalidDocumentTransition,
)
from app.documents.repository import (
    DocumentNotFound,
    DocumentRepository,
    IdempotencyConflict,
)
from app.documents.storage import (
    DocumentStore,
    ObjectVerificationError,
    quarantine_object_key,
)
from app.schemas.document import (
    DocumentFinalizeRequest,
    DocumentInitiateRequest,
    DocumentResponse,
    DocumentUploadGrantResponse,
    DocumentVersionRequest,
)

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
_UPLOAD_ROLES = frozenset({"doctor", "nurse", "receptionist"})


def _authorized_identity(user: TokenPayload) -> tuple[UUID, UUID, set[UUID]]:
    if user.role not in _UPLOAD_ROLES:
        raise HTTPException(status_code=403, detail="Document registration role required")
    try:
        tenant_id = UUID(user.tenant_id)
        actor_id = UUID(user.user_id)
        facility_ids = {UUID(value) for value in user.facility_ids}
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="Invalid authorization scope") from exc
    return tenant_id, actor_id, facility_ids


def _authorized_ids(user: TokenPayload, facility_id: UUID) -> tuple[UUID, UUID]:
    tenant_id, actor_id, facility_ids = _authorized_identity(user)
    if facility_id not in facility_ids:
        raise HTTPException(status_code=403, detail="Facility access denied")
    return tenant_id, actor_id


@router.post("", response_model=DocumentResponse)
async def initiate_document(
    body: DocumentInitiateRequest,
    response: Response,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
    ),
    user: TokenPayload = Depends(get_current_user),
    repository: DocumentRepository = Depends(get_document_repository),
    purpose_authorizer: DocumentPurposeAuthorizer = Depends(
        get_document_purpose_authorizer
    ),
) -> DocumentRegistryEntry:
    tenant_id, actor_id = _authorized_ids(user, body.facility_id)
    try:
        await purpose_authorizer.authorize(
            tenant_id=tenant_id,
            patient_id=body.patient_id,
            encounter_id=body.encounter_id,
            purpose=body.purpose,
            consent_reference=body.consent_reference,
        )
    except ConsentAuthorizationDenied as exc:
        raise HTTPException(
            status_code=403,
            detail="Active consent does not authorize this upload",
        ) from exc
    document = DocumentRegistryEntry(
        tenant_id=tenant_id,
        facility_id=body.facility_id,
        patient_id=body.patient_id,
        encounter_id=body.encounter_id,
        uploader_actor_id=actor_id,
        purpose=body.purpose,
        consent_reference=body.consent_reference,
        original_filename=body.original_filename,
        declared_document_class=body.declared_document_class,
        declared_mime=body.declared_mime,
        declared_size_bytes=body.declared_size_bytes,
        idempotency_key=idempotency_key,
        upload_expires_at=datetime.now(UTC)
        + timedelta(seconds=settings.DOCUMENT_UPLOAD_SESSION_TTL_SECONDS),
    )
    try:
        result = await repository.create(document)
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail="Idempotency key conflict") from exc

    response.status_code = 201 if result.created else 200
    audit_emitter.emit(
        tenant_id=tenant_id,
        facility_id=body.facility_id,
        actor_id=actor_id,
        actor_type="staff",
        actor_role=user.role,
        action="document_register" if result.created else "document_register_replay",
        resource_type="document",
        resource_id=result.document.id,
        purpose=body.purpose,
        audit_metadata={"state": result.document.state.value},
    )
    return result.document


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document_status(
    document_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    repository: DocumentRepository = Depends(get_document_repository),
) -> DocumentRegistryEntry:
    document, _actor_id = await _authorized_document(document_id, user, repository)
    return document


@router.post("/{document_id}/cancel", response_model=DocumentResponse)
async def cancel_document_upload(
    document_id: UUID,
    body: DocumentVersionRequest,
    user: TokenPayload = Depends(get_current_user),
    repository: DocumentRepository = Depends(get_document_repository),
) -> DocumentRegistryEntry:
    document, actor_id = await _authorized_document(document_id, user, repository)
    try:
        cancelled = await repository.cancel(
            tenant_id=document.tenant_id,
            document_id=document.id,
            expected_version=body.expected_version,
        )
    except (ConcurrentDocumentUpdate, InvalidDocumentTransition) as exc:
        raise HTTPException(status_code=409, detail="Document state conflict") from exc
    audit_emitter.emit(
        tenant_id=cancelled.tenant_id,
        facility_id=cancelled.facility_id,
        actor_id=actor_id,
        actor_type="staff",
        actor_role=user.role,
        action="document_upload_cancel",
        resource_type="document",
        resource_id=cancelled.id,
        purpose=cancelled.purpose,
        audit_metadata={"state": cancelled.state.value, "version": cancelled.version},
    )
    return cancelled


async def _authorized_document(
    document_id: UUID,
    user: TokenPayload,
    repository: DocumentRepository,
) -> tuple[DocumentRegistryEntry, UUID]:
    tenant_id, actor_id, facility_ids = _authorized_identity(user)
    try:
        document = await repository.get(tenant_id, document_id)
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    if document.facility_id not in facility_ids:
        raise HTTPException(status_code=403, detail="Facility access denied")
    return document, actor_id


@router.post("/{document_id}/upload-session", response_model=DocumentUploadGrantResponse)
async def create_upload_session(
    document_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    repository: DocumentRepository = Depends(get_document_repository),
    store: DocumentStore = Depends(get_document_store),
) -> DocumentUploadGrantResponse:
    document, _actor_id = await _authorized_document(document_id, user, repository)
    try:
        grant = await store.create_upload_grant(document)
    except ObjectVerificationError as exc:
        raise HTTPException(status_code=409, detail="Document cannot receive an upload grant") from exc
    return DocumentUploadGrantResponse(
        url=grant.url,
        expires_in_seconds=grant.expires_in_seconds,
        required_headers=grant.required_headers,
    )


@router.post("/{document_id}/finalize", response_model=DocumentResponse)
async def finalize_document_upload(
    document_id: UUID,
    body: DocumentFinalizeRequest,
    user: TokenPayload = Depends(get_current_user),
    repository: DocumentRepository = Depends(get_document_repository),
    store: DocumentStore = Depends(get_document_store),
) -> DocumentRegistryEntry:
    document, actor_id = await _authorized_document(document_id, user, repository)
    object_key = quarantine_object_key(document)
    try:
        verified = await store.verify_upload(document, object_key)
        finalized = await repository.finalize_upload(
            tenant_id=document.tenant_id,
            document_id=document.id,
            expected_version=body.expected_version,
            object_key=verified.object_key,
            checksum_sha256=verified.checksum_sha256,
            detected_mime=verified.detected_mime,
        )
    except ObjectVerificationError as exc:
        raise HTTPException(status_code=422, detail="Uploaded object verification failed") from exc
    except (ConcurrentDocumentUpdate, InvalidDocumentTransition) as exc:
        raise HTTPException(status_code=409, detail="Document state conflict") from exc

    audit_emitter.emit(
        tenant_id=finalized.tenant_id,
        facility_id=finalized.facility_id,
        actor_id=actor_id,
        actor_type="staff",
        actor_role=user.role,
        action="document_upload_finalize",
        resource_type="document",
        resource_id=finalized.id,
        purpose=finalized.purpose,
        audit_metadata={"state": finalized.state.value, "version": finalized.version},
    )
    return finalized
