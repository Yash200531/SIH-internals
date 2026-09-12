"""Authenticated, consent-scoped intake review and explicit clinician confirmation."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.audit.emitter import audit_emitter
from app.auth.dependencies import require_clinician
from app.auth.token import TokenPayload
from app.config import settings
from app.database import get_postgres_pool
from app.patient_portal.worklist import IntakeHandoff, PostgresIntakeWorklist
from app.summary_workflow.context import SummaryContextRepository
from app.summary_workflow.contracts import ConfirmedEncounterContext, ConfirmEncounterContextCommand
from app.summary_workflow.dependencies import get_summary_context_repository
from app.summary_workflow.repository import SummaryConflict

router = APIRouter(prefix="/api/v1/intake-worklist", tags=["intake-worklist"])


async def get_worklist() -> PostgresIntakeWorklist:
    if not settings.DOCUMENT_WORKFLOW_ENABLED:
        raise HTTPException(503, "Patient intake workflow is not enabled")
    return PostgresIntakeWorklist(await get_postgres_pool())


def scope(user: TokenPayload) -> tuple[UUID, UUID, set[UUID]]:
    try:
        tenant, actor = UUID(user.tenant_id), UUID(user.user_id)
        facilities = {UUID(value) for value in user.facility_ids}
    except (TypeError, ValueError) as exc:
        raise HTTPException(403, "Invalid clinical authorization scope") from exc
    if not facilities:
        raise HTTPException(403, "Facility access required")
    return tenant, actor, facilities


def audit(user: TokenPayload, action: str, intake_id: UUID | None, outcome="success"):
    tenant, actor, _ = scope(user)
    audit_emitter.emit(
        tenant_id=tenant, actor_id=actor, actor_type="staff", actor_role=user.role,
        action=action, resource_type="patient_intake", resource_id=intake_id,
        purpose="treatment", outcome=outcome,
    )


@router.get("", response_model=list[IntakeHandoff])
async def list_intakes(
    response: Response, purpose: Literal["treatment"] = Query(...),
    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=10000),
    user: TokenPayload = Depends(require_clinician),
    repository: PostgresIntakeWorklist = Depends(get_worklist),
) -> list[IntakeHandoff]:
    tenant, _, facilities = scope(user)
    response.headers["Cache-Control"] = "private, no-store"
    items = await repository.read(tenant, facilities, limit=limit, offset=offset)
    audit(user, "list", None)
    return items


class ConfirmIntake(BaseModel):
    reviewed: Literal[True]
    expected_version: int | None = Field(default=None, ge=1)


@router.post("/{intake_id}/confirm", response_model=ConfirmedEncounterContext)
async def confirm_intake(
    intake_id: UUID, body: ConfirmIntake, response: Response,
    user: TokenPayload = Depends(require_clinician),
    repository: PostgresIntakeWorklist = Depends(get_worklist),
    contexts: SummaryContextRepository = Depends(get_summary_context_repository),
) -> ConfirmedEncounterContext:
    tenant, actor, facilities = scope(user)
    response.headers["Cache-Control"] = "private, no-store"
    items = await repository.read(tenant, facilities, intake_id=intake_id, limit=1)
    if not items:
        audit(user, "confirm", intake_id, "denied")
        raise HTTPException(404, "Accepted intake with active consent not found")
    intake = items[0]
    try:
        confirmed = await contexts.confirm(
            tenant_id=tenant, actor_id=actor,
            command=ConfirmEncounterContextCommand(
                facility_id=intake.facility_id, patient_id=intake.patient_id,
                encounter_id=intake.encounter_id, language=intake.language,
                chief_complaint=intake.chief_complaint,
                confirmed_answers=intake.confirmed_answers,
                expected_version=body.expected_version,
            ),
        )
    except SummaryConflict as exc:
        audit(user, "confirm", intake_id, "failure")
        raise HTTPException(409, "Context changed; reload before confirming") from exc
    audit(user, "confirm", intake_id)
    return confirmed
