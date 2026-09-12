"""Authorized Phase 8 evidence-linked summary lifecycle API."""

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.auth.dependencies import get_current_user
from app.auth.token import TokenPayload
from app.summary_workflow.context import SummaryContextRepository
from app.summary_workflow.contracts import (
    ConfirmedEncounterContext,
    ConfirmEncounterContextCommand,
    EditSummaryCommand,
    GenerateSummaryCommand,
    RegenerateSummaryCommand,
    RejectSummaryCommand,
    SummaryAction,
    SummaryRecord,
    VersionCommand,
)
from app.summary_workflow.dependencies import (
    get_summary_context_repository,
    get_summary_repository,
    get_summary_workflow_service,
)
from app.summary_workflow.repository import SummaryConflict, SummaryNotFound, SummaryRepository
from app.summary_workflow.service import (
    SummaryPermissionError,
    SummaryTransitionError,
    SummaryWorkflowService,
)

router = APIRouter(prefix="/api/v1/summary-workflows", tags=["summary-workflows"])


def _identity(user: TokenPayload) -> tuple[UUID, UUID, set[UUID]]:
    if user.role not in {"doctor", "nurse"}:
        raise HTTPException(status_code=403, detail="Clinical summary role required")
    try:
        tenant_id = UUID(user.tenant_id)
        actor_id = UUID(user.user_id)
        facility_ids = {UUID(item) for item in user.facility_ids}
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="Invalid authorization scope") from exc
    if not facility_ids:
        raise HTTPException(status_code=403, detail="Facility access required")
    return tenant_id, actor_id, facility_ids


def _require_facility(facility_id: UUID, allowed: set[UUID]) -> None:
    if facility_id not in allowed:
        raise HTTPException(status_code=403, detail="Facility access denied")


def _raise_workflow(exc: Exception) -> None:
    if isinstance(exc, SummaryNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, SummaryConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, SummaryPermissionError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, SummaryTransitionError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.put("/contexts", response_model=ConfirmedEncounterContext)
async def confirm_encounter_context(
    body: ConfirmEncounterContextCommand,
    user: TokenPayload = Depends(get_current_user),
    repository: SummaryContextRepository = Depends(get_summary_context_repository),
) -> ConfirmedEncounterContext:
    tenant_id, actor_id, facilities = _identity(user)
    _require_facility(body.facility_id, facilities)
    try:
        return await repository.confirm(tenant_id=tenant_id, actor_id=actor_id, command=body)
    except Exception as exc:
        _raise_workflow(exc)
        raise


@router.post("/generate", response_model=SummaryRecord, status_code=201)
async def generate_summary_draft(
    body: GenerateSummaryCommand,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=128),
    user: TokenPayload = Depends(get_current_user),
    context_repository: SummaryContextRepository = Depends(get_summary_context_repository),
    service: SummaryWorkflowService = Depends(get_summary_workflow_service),
) -> SummaryRecord:
    tenant_id, actor_id, facilities = _identity(user)
    _require_facility(body.facility_id, facilities)
    try:
        source = await context_repository.assemble(
            tenant_id=tenant_id, facility_id=body.facility_id,
            patient_id=body.patient_id, encounter_id=body.encounter_id,
            language=body.language,
        )
        return await service.generate(
            source=source, actor_id=actor_id, actor_role=user.role,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_workflow(exc)
        raise


@router.get("", response_model=list[SummaryRecord])
async def list_summaries(
    encounter_id: UUID = Query(...), user: TokenPayload = Depends(get_current_user),
    repository: SummaryRepository = Depends(get_summary_repository),
) -> list[SummaryRecord]:
    tenant_id, _actor_id, facilities = _identity(user)
    records = await repository.list_for_encounter(tenant_id=tenant_id, encounter_id=encounter_id)
    return [record for record in records if record.facility_id in facilities]


@router.get("/{summary_id}", response_model=SummaryRecord)
async def get_summary(
    summary_id: UUID, user: TokenPayload = Depends(get_current_user),
    repository: SummaryRepository = Depends(get_summary_repository),
) -> SummaryRecord:
    tenant_id, _actor_id, facilities = _identity(user)
    try:
        record = await repository.get(tenant_id=tenant_id, summary_id=summary_id)
        _require_facility(record.facility_id, facilities)
        return record
    except Exception as exc:
        _raise_workflow(exc)
        raise


@router.get("/{summary_id}/history", response_model=list[SummaryAction])
async def get_summary_history(
    summary_id: UUID, user: TokenPayload = Depends(get_current_user),
    repository: SummaryRepository = Depends(get_summary_repository),
) -> list[SummaryAction]:
    await get_summary(summary_id, user, repository)
    tenant_id, _actor_id, _facilities = _identity(user)
    return await repository.history(tenant_id=tenant_id, summary_id=summary_id)


async def _authorized_record(
    summary_id: UUID, user: TokenPayload, repository: SummaryRepository
) -> tuple[UUID, UUID, SummaryRecord]:
    tenant_id, actor_id, facilities = _identity(user)
    record = await repository.get(tenant_id=tenant_id, summary_id=summary_id)
    _require_facility(record.facility_id, facilities)
    return tenant_id, actor_id, record


@router.patch("/{summary_id}/draft", response_model=SummaryRecord)
async def edit_summary_draft(
    summary_id: UUID, body: EditSummaryCommand,
    user: TokenPayload = Depends(get_current_user),
    repository: SummaryRepository = Depends(get_summary_repository),
    service: SummaryWorkflowService = Depends(get_summary_workflow_service),
) -> SummaryRecord:
    try:
        tenant_id, actor_id, _record = await _authorized_record(summary_id, user, repository)
        return await service.edit(
            tenant_id=tenant_id, summary_id=summary_id, actor_id=actor_id,
            actor_role=user.role, expected_version=body.expected_version, content=body.content,
        )
    except Exception as exc:
        _raise_workflow(exc)
        raise


async def _transition(
    summary_id: UUID, body: VersionCommand, user: TokenPayload,
    repository: SummaryRepository, service: SummaryWorkflowService, action: str,
) -> SummaryRecord:
    tenant_id, actor_id, _record = await _authorized_record(summary_id, user, repository)
    method = getattr(service, action)
    return await method(
        tenant_id=tenant_id, summary_id=summary_id, actor_id=actor_id,
        actor_role=user.role, expected_version=body.expected_version,
    )


@router.post("/{summary_id}/submit-review", response_model=SummaryRecord)
async def submit_summary_review(
    summary_id: UUID, body: VersionCommand, user: TokenPayload = Depends(get_current_user),
    repository: SummaryRepository = Depends(get_summary_repository),
    service: SummaryWorkflowService = Depends(get_summary_workflow_service),
) -> SummaryRecord:
    try:
        return await _transition(summary_id, body, user, repository, service, "submit")
    except Exception as exc:
        _raise_workflow(exc)
        raise


@router.post("/{summary_id}/reject", response_model=SummaryRecord)
async def reject_summary(
    summary_id: UUID, body: RejectSummaryCommand,
    user: TokenPayload = Depends(get_current_user),
    repository: SummaryRepository = Depends(get_summary_repository),
    service: SummaryWorkflowService = Depends(get_summary_workflow_service),
) -> SummaryRecord:
    try:
        tenant_id, actor_id, _record = await _authorized_record(summary_id, user, repository)
        return await service.reject(
            tenant_id=tenant_id, summary_id=summary_id, actor_id=actor_id,
            actor_role=user.role, expected_version=body.expected_version, reason=body.reason,
        )
    except Exception as exc:
        _raise_workflow(exc)
        raise


@router.post("/{summary_id}/sign", response_model=SummaryRecord)
async def sign_summary(
    summary_id: UUID, body: VersionCommand, user: TokenPayload = Depends(get_current_user),
    repository: SummaryRepository = Depends(get_summary_repository),
    service: SummaryWorkflowService = Depends(get_summary_workflow_service),
) -> SummaryRecord:
    try:
        return await _transition(summary_id, body, user, repository, service, "sign")
    except Exception as exc:
        _raise_workflow(exc)
        raise


@router.post("/{summary_id}/regenerate", response_model=SummaryRecord, status_code=201)
async def regenerate_summary(
    summary_id: UUID, body: RegenerateSummaryCommand,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=128),
    user: TokenPayload = Depends(get_current_user),
    repository: SummaryRepository = Depends(get_summary_repository),
    context_repository: SummaryContextRepository = Depends(get_summary_context_repository),
    service: SummaryWorkflowService = Depends(get_summary_workflow_service),
) -> SummaryRecord:
    tenant_id, actor_id, facilities = _identity(user)
    _require_facility(body.facility_id, facilities)
    try:
        previous = await repository.get(tenant_id=tenant_id, summary_id=summary_id)
        _require_facility(previous.facility_id, facilities)
        source = await context_repository.assemble(
            tenant_id=tenant_id, facility_id=body.facility_id,
            patient_id=body.patient_id, encounter_id=body.encounter_id,
            language=body.language,
        )
        return await service.regenerate(
            source=source, previous_summary_id=summary_id, actor_id=actor_id,
            actor_role=user.role, expected_version=body.expected_version,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_workflow(exc)
        raise
