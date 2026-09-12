"""Authorized access to reviewed facts and their rebuildable projections."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.audit.emitter import audit_emitter
from app.auth.dependencies import get_current_user
from app.auth.token import TokenPayload
from app.documents.dependencies import get_reviewed_fact_repository
from app.documents.promotion import PostgresReviewedFactRepository
from app.documents.repository import DocumentNotFound
from app.schemas.reviewed_document import (
    ReviewedFactResponse,
    TimelineEntryResponse,
    WithdrawalRequest,
    WithdrawalResponse,
)

router = APIRouter(prefix="/api/v1/reviewed-documents", tags=["reviewed-documents"])


def _identity(user: TokenPayload) -> tuple[UUID, UUID, set[UUID]]:
    if user.role not in {"doctor", "nurse"}:
        raise HTTPException(status_code=403, detail="Clinical record role required")
    try:
        return (
            UUID(user.tenant_id),
            UUID(user.user_id),
            {UUID(value) for value in user.facility_ids},
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="Invalid authorization scope") from exc


@router.get("/documents/{document_id}/facts", response_model=list[ReviewedFactResponse])
async def list_reviewed_document_facts(
    document_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    repository: PostgresReviewedFactRepository = Depends(
        get_reviewed_fact_repository
    ),
) -> list[ReviewedFactResponse]:
    tenant_id, _actor_id, facility_ids = _identity(user)
    try:
        facts = await repository.list_facts(
            tenant_id=tenant_id,
            document_id=document_id,
            facility_ids=facility_ids,
        )
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return [ReviewedFactResponse.model_validate(fact) for fact in facts]


@router.get("/patients/{patient_id}/timeline", response_model=list[TimelineEntryResponse])
async def list_document_timeline(
    patient_id: UUID,
    limit: int = Query(default=100, ge=1, le=200),
    user: TokenPayload = Depends(get_current_user),
    repository: PostgresReviewedFactRepository = Depends(
        get_reviewed_fact_repository
    ),
) -> list[TimelineEntryResponse]:
    tenant_id, _actor_id, facility_ids = _identity(user)
    entries = await repository.list_timeline(
        tenant_id=tenant_id,
        patient_id=patient_id,
        facility_ids=facility_ids,
        limit=limit,
    )
    return [TimelineEntryResponse.model_validate(entry) for entry in entries]


@router.get("/documents/{document_id}/fhir", response_model=list[dict[str, object]])
async def list_reviewed_document_fhir(
    document_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    repository: PostgresReviewedFactRepository = Depends(
        get_reviewed_fact_repository
    ),
) -> list[dict[str, object]]:
    tenant_id, _actor_id, facility_ids = _identity(user)
    try:
        return await repository.list_fhir_resources(
            tenant_id=tenant_id,
            document_id=document_id,
            facility_ids=facility_ids,
        )
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/documents/{document_id}/withdraw", response_model=WithdrawalResponse)
async def withdraw_reviewed_document_facts(
    document_id: UUID,
    body: WithdrawalRequest,
    user: TokenPayload = Depends(get_current_user),
    repository: PostgresReviewedFactRepository = Depends(
        get_reviewed_fact_repository
    ),
) -> WithdrawalResponse:
    tenant_id, actor_id, facility_ids = _identity(user)
    try:
        count = await repository.withdraw(
            tenant_id=tenant_id,
            document_id=document_id,
            actor_id=actor_id,
            actor_role=user.role,
            reason_code=body.reason_code,
            facility_ids=facility_ids,
        )
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit_emitter.emit(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_type="staff",
        actor_role=user.role,
        action="reviewed_document_facts_withdraw",
        resource_type="document",
        resource_id=document_id,
        purpose="treatment",
        audit_metadata={
            "withdrawn_fact_count": count,
            "reason_code": body.reason_code,
        },
    )
    return WithdrawalResponse(document_id=document_id, withdrawn_fact_count=count)
