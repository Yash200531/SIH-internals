"""Authorized nurse/doctor workflow for source-adjacent document review."""

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.audit.emitter import audit_emitter
from app.auth.dependencies import get_current_user
from app.auth.token import TokenPayload
from app.documents.dependencies import (
    get_document_review_repository,
    get_document_store,
)
from app.documents.registry import ConcurrentDocumentUpdate, DocumentRegistryEntry
from app.documents.repository import DocumentNotFound
from app.documents.review import (
    CandidateDecision,
    ManualCandidate,
    ReviewConflict,
    ReviewIncomplete,
)
from app.documents.review_repository import DocumentReviewRepository
from app.documents.storage import DocumentStore, ObjectVerificationError
from app.schemas.document_review import (
    CandidateDecisionRequest,
    ManualCandidateRequest,
    OpenManualReviewRequest,
    PagePreviewResponse,
    ReviewCandidateResponse,
    ReviewDocumentResponse,
    ReviewFinalizeRequest,
    ReviewQueueItemResponse,
)

router = APIRouter(prefix="/api/v1/document-reviews", tags=["document-reviews"])
_REVIEW_ROLES = frozenset({"doctor", "nurse"})


def _review_identity(user: TokenPayload) -> tuple[UUID, UUID, set[UUID]]:
    if user.role not in _REVIEW_ROLES:
        raise HTTPException(status_code=403, detail="Clinical review role required")
    try:
        tenant_id = UUID(user.tenant_id)
        actor_id = UUID(user.user_id)
        facility_ids = {UUID(value) for value in user.facility_ids}
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="Invalid authorization scope") from exc
    if not facility_ids:
        raise HTTPException(status_code=403, detail="Facility access required")
    return tenant_id, actor_id, facility_ids


@router.get("", response_model=list[ReviewQueueItemResponse])
async def list_document_review_queue(
    limit: int = Query(default=100, ge=1, le=200),
    user: TokenPayload = Depends(get_current_user),
    repository: DocumentReviewRepository = Depends(get_document_review_repository),
) -> list[ReviewQueueItemResponse]:
    tenant_id, _actor_id, facility_ids = _review_identity(user)
    items = await repository.list_queue(
        tenant_id=tenant_id,
        facility_ids=facility_ids,
        limit=limit,
    )
    return [ReviewQueueItemResponse.model_validate(item) for item in items]


@router.get("/{document_id}", response_model=ReviewDocumentResponse)
async def get_document_review(
    document_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    repository: DocumentReviewRepository = Depends(get_document_review_repository),
) -> ReviewDocumentResponse:
    tenant_id, _actor_id, facility_ids = _review_identity(user)
    try:
        review = await repository.get(tenant_id=tenant_id, document_id=document_id)
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    if review.facility_id not in facility_ids:
        raise HTTPException(status_code=403, detail="Facility access denied")
    return ReviewDocumentResponse.model_validate(review)


@router.post("/{document_id}/manual", response_model=ReviewDocumentResponse)
async def open_manual_document_review(
    document_id: UUID,
    body: OpenManualReviewRequest,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
    ),
    user: TokenPayload = Depends(get_current_user),
    repository: DocumentReviewRepository = Depends(get_document_review_repository),
) -> ReviewDocumentResponse:
    tenant_id, actor_id, facility_ids = _review_identity(user)
    try:
        review = await repository.open_manual_review(
            tenant_id=tenant_id,
            document_id=document_id,
            facility_ids=facility_ids,
            actor_id=actor_id,
            actor_role=user.role,
            expected_document_version=body.expected_document_version,
            idempotency_key=idempotency_key,
        )
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ReviewConflict, ConcurrentDocumentUpdate) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewIncomplete as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit_emitter.emit(
        tenant_id=tenant_id,
        facility_id=review.facility_id,
        actor_id=actor_id,
        actor_type="staff",
        actor_role=user.role,
        action="document_manual_review_open",
        resource_type="document",
        resource_id=document_id,
        purpose=review.purpose,
        audit_metadata={"state": review.state, "page_count": len(review.pages)},
    )
    return ReviewDocumentResponse.model_validate(review)


@router.post(
    "/{document_id}/candidates/{candidate_id}/decisions",
    response_model=ReviewCandidateResponse,
)
async def decide_document_candidate(
    document_id: UUID,
    candidate_id: UUID,
    body: CandidateDecisionRequest,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
    ),
    user: TokenPayload = Depends(get_current_user),
    repository: DocumentReviewRepository = Depends(get_document_review_repository),
) -> ReviewCandidateResponse:
    tenant_id, actor_id, facility_ids = _review_identity(user)
    try:
        review = await repository.get(tenant_id=tenant_id, document_id=document_id)
        if review.facility_id not in facility_ids:
            raise PermissionError("Facility access denied")
        candidate = await repository.decide(
            tenant_id=tenant_id,
            document_id=document_id,
            facility_ids=facility_ids,
            actor_id=actor_id,
            actor_role=user.role,
            idempotency_key=idempotency_key,
            candidate_id=candidate_id,
            decision=CandidateDecision(
                action=body.action,
                expected_candidate_version=body.expected_candidate_version,
                corrected_value=body.corrected_value,
                corrected_unit=body.corrected_unit,
                reason_code=body.reason_code,
                source_verified=body.source_verified,
            ),
        )
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="Document or candidate not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ReviewConflict, ConcurrentDocumentUpdate) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit_emitter.emit(
        tenant_id=tenant_id,
        facility_id=review.facility_id,
        actor_id=actor_id,
        actor_type="staff",
        actor_role=user.role,
        action=f"document_review_{body.action.value}",
        resource_type="document_candidate",
        resource_id=candidate_id,
        purpose="treatment",
        audit_metadata={
            "document_id": str(document_id),
            "candidate_version": candidate.version,
        },
    )
    return ReviewCandidateResponse.model_validate(candidate)


@router.post("/{document_id}/candidates", response_model=ReviewCandidateResponse)
async def add_manual_document_candidate(
    document_id: UUID,
    body: ManualCandidateRequest,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
    ),
    user: TokenPayload = Depends(get_current_user),
    repository: DocumentReviewRepository = Depends(get_document_review_repository),
) -> ReviewCandidateResponse:
    tenant_id, actor_id, facility_ids = _review_identity(user)
    try:
        review = await repository.get(tenant_id=tenant_id, document_id=document_id)
        if review.facility_id not in facility_ids:
            raise PermissionError("Facility access denied")
        candidate = await repository.add_manual_candidate(
            tenant_id=tenant_id,
            document_id=document_id,
            facility_ids=facility_ids,
            actor_id=actor_id,
            actor_role=user.role,
            idempotency_key=idempotency_key,
            candidate=ManualCandidate(
                entity_type=body.entity_type,
                normalized_value=body.normalized_value,
                unit=body.unit,
                source_page_artifact_id=body.source_page_artifact_id,
                source_page_number=body.source_page_number,
                source_verified=body.source_verified,
            ),
        )
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="Document or source page not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ReviewConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit_emitter.emit(
        tenant_id=tenant_id,
        facility_id=review.facility_id,
        actor_id=actor_id,
        actor_type="staff",
        actor_role=user.role,
        action="document_review_manual_entry",
        resource_type="document_candidate",
        resource_id=candidate.candidate_id,
        purpose=review.purpose,
        audit_metadata={
            "document_id": str(document_id),
            "candidate_version": candidate.version,
            "entity_type": candidate.entity_type,
        },
    )
    return ReviewCandidateResponse.model_validate(candidate)


@router.post("/{document_id}/finalize", response_model=ReviewDocumentResponse)
async def finalize_document_review(
    document_id: UUID,
    body: ReviewFinalizeRequest,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
    ),
    user: TokenPayload = Depends(get_current_user),
    repository: DocumentReviewRepository = Depends(get_document_review_repository),
) -> ReviewDocumentResponse:
    tenant_id, actor_id, facility_ids = _review_identity(user)
    try:
        review = await repository.finalize(
            tenant_id=tenant_id,
            document_id=document_id,
            facility_ids=facility_ids,
            actor_id=actor_id,
            actor_role=user.role,
            expected_document_version=body.expected_document_version,
            idempotency_key=idempotency_key,
        )
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ReviewConflict, ConcurrentDocumentUpdate) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewIncomplete as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit_emitter.emit(
        tenant_id=tenant_id,
        facility_id=review.facility_id,
        actor_id=actor_id,
        actor_type="staff",
        actor_role=user.role,
        action="document_review_finalize",
        resource_type="document",
        resource_id=document_id,
        purpose=review.purpose,
        audit_metadata={"state": review.state, "version": review.version},
    )
    return ReviewDocumentResponse.model_validate(review)


@router.get(
    "/{document_id}/pages/{page_artifact_id}/preview",
    response_model=PagePreviewResponse,
)
async def create_review_page_preview(
    document_id: UUID,
    page_artifact_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    repository: DocumentReviewRepository = Depends(get_document_review_repository),
    store: DocumentStore = Depends(get_document_store),
) -> PagePreviewResponse:
    tenant_id, actor_id, facility_ids = _review_identity(user)
    try:
        review = await repository.get(tenant_id=tenant_id, document_id=document_id)
        if review.facility_id not in facility_ids:
            raise PermissionError("Facility access denied")
        page = await repository.get_page(
            tenant_id=tenant_id,
            document_id=document_id,
            page_artifact_id=page_artifact_id,
        )
        grant = await store.create_page_preview_grant(
            # A registry-shaped object is deliberately fetched through the
            # durable repository boundary before signing the exact page key.
            await _review_document_as_registry(repository, tenant_id, document_id),
            page,
        )
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="Document page not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ObjectVerificationError as exc:
        raise HTTPException(status_code=503, detail="Source preview is unavailable") from exc
    audit_emitter.emit(
        tenant_id=tenant_id,
        facility_id=review.facility_id,
        actor_id=actor_id,
        actor_type="staff",
        actor_role=user.role,
        action="document_source_preview",
        resource_type="document_page",
        resource_id=page_artifact_id,
        purpose=review.purpose,
        audit_metadata={"document_id": str(document_id)},
    )
    return PagePreviewResponse(url=grant.url, expires_in_seconds=grant.expires_in_seconds)


async def _review_document_as_registry(
    repository: DocumentReviewRepository,
    tenant_id: UUID,
    document_id: UUID,
) -> DocumentRegistryEntry:
    return await repository.get_registry(
        tenant_id=tenant_id,
        document_id=document_id,
    )
