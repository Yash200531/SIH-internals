"""Authenticated durable prototype alert queue and clinical receipt/disposition."""

import hashlib
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.auth.dependencies import require_clinician
from app.auth.token import TokenPayload
from app.config import settings
from app.database import get_postgres_pool
from app.patient_portal.worklist import PostgresIntakeWorklist
from app.routers.intake_worklist import get_worklist, scope
from app.rules.alert_lifecycle import AlertActor, AlertCommand, AlertConflict, AlertLifecycle
from app.rules.alert_repository import AlertEvidence, AlertNotFound, PostgresAlertRepository
from app.rules.triage import evaluate_text_sources

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


async def get_alert_repository() -> PostgresAlertRepository:
    if not settings.TRIAGE_WORKFLOW_ENABLED:
        raise HTTPException(503, "Durable alert workflow is not enabled")
    return PostgresAlertRepository(await get_postgres_pool())


def alert_actor(user: TokenPayload = Depends(require_clinician)) -> AlertActor:
    tenant, actor, facilities = scope(user)
    return AlertActor(actor_id=actor, tenant_id=tenant, facility_ids=frozenset(facilities), role=user.role)


class EvaluateIntake(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewed: Literal[True]


@router.post("/from-intake/{intake_id}")
async def evaluate_intake(
    intake_id: UUID,
    body: EvaluateIntake,
    response: Response,
    purpose: Literal["treatment"] = Query(...),
    actor: AlertActor = Depends(alert_actor),
    worklist: PostgresIntakeWorklist = Depends(get_worklist),
    repository: PostgresAlertRepository = Depends(get_alert_repository),
):
    if not settings.ENABLE_DEMO_ROUTES:
        raise HTTPException(503, "Prototype rules are restricted to the local demo")
    response.headers["Cache-Control"] = "private, no-store"
    items = await worklist.read(
        actor.tenant_id, set(actor.facility_ids), intake_id=intake_id, limit=1
    )
    if not items:
        raise HTTPException(404, "Consented accepted intake not found")
    item = items[0]
    sources = {
        "chief_complaint": item.chief_complaint,
        **{f"confirmed_answers.{key}": value for key, value in item.confirmed_answers.items()},
    }
    evaluation = evaluate_text_sources(sources)
    # Accepted intakes are immutable. The stable source ID and content fingerprint
    # keep retries identical independently of later summary-context revisions.
    fingerprint = hashlib.sha256(
        json.dumps(
            {"intake_id": str(item.id), "sources": sources}, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    alerts = []
    for rule in evaluation.flags:
        alerts.append(
            await repository.raise_flag(
                actor=actor,
                facility_id=item.facility_id,
                encounter_id=item.encounter_id,
                evidence=AlertEvidence(input_version=1, fingerprint=fingerprint),
                rule=rule,
            )
        )
    return {
        "outcome": evaluation.outcome,
        "alerts": alerts,
        "approval_status": "prototype_only",
        "no_match_is_not_safe_or_routine": True,
        "staff_notification_sent": False,
    }


@router.get("")
async def list_alerts(
    response: Response,
    purpose: Literal["treatment"] = Query(...),
    limit: int = Query(100, ge=1, le=200),
    include_closed: bool = False,
    actor: AlertActor = Depends(alert_actor),
    repository: PostgresAlertRepository = Depends(get_alert_repository),
):
    response.headers["Cache-Control"] = "private, no-store"
    return await repository.list_flags(actor, limit=limit, include_closed=include_closed)


class ClinicalAlertCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["acknowledge", "resolve"]
    expected_version: int = Field(ge=1)
    reason_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    rationale: str | None = Field(default=None, min_length=1, max_length=2000)


@router.post("/{flag_id}/commands", response_model=AlertLifecycle)
async def command_alert(
    flag_id: UUID,
    body: ClinicalAlertCommand,
    response: Response,
    purpose: Literal["treatment"] = Query(...),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=128),
    actor: AlertActor = Depends(alert_actor),
    repository: PostgresAlertRepository = Depends(get_alert_repository),
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return await repository.command(
            flag_id=flag_id,
            actor=actor,
            command=AlertCommand.model_validate(body.model_dump()),
            idempotency_key=idempotency_key,
        )
    except AlertNotFound as exc:
        raise HTTPException(404, "Alert not found") from exc
    except AlertConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
