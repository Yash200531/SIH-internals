from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.audit.emitter import audit_emitter, safe_uuid
from app.auth.dependencies import get_current_user
from app.auth.token import TokenPayload
from app.models.encounter import VALID_TRANSITIONS, Encounter
from app.schemas.encounter import EncounterCreate, EncounterStatusUpdate

router = APIRouter(prefix="/api/v1/encounters", tags=["encounters"])

_encounters: dict[str, Encounter] = {}


def _to_response(e: Encounter) -> dict:
    return {
        "id": e.id,
        "tenant_id": e.tenant_id,
        "patient_id": e.patient_id,
        "facility_id": e.facility_id,
        "status": e.status,
        "encounter_type": e.encounter_type,
        "chief_complaint": e.chief_complaint,
        "created_at": e.created_at,
        "version": e.version,
    }


@router.post("", status_code=201)
async def create_encounter(
    body: EncounterCreate,
    tenant_id: UUID = Query(...),
    user: TokenPayload = Depends(get_current_user),
):
    encounter = Encounter(
        tenant_id=tenant_id,
        facility_id=body.facility_id,
        patient_id=body.patient_id,
        department_id=body.department_id,
        encounter_type=body.encounter_type,
        chief_complaint=body.chief_complaint,
    )
    _encounters[str(encounter.id)] = encounter

    audit_emitter.emit(
        tenant_id=tenant_id,
        actor_id=safe_uuid(user.user_id),
        actor_type="staff",
        actor_role=user.role,
        action="create",
        resource_type="encounter",
        resource_id=encounter.id,
        outcome="success",
        audit_metadata={"encounter_type": body.encounter_type},
    )

    return _to_response(encounter)


@router.get("", response_model=List[dict])
async def list_encounters(
    patient_id: Optional[UUID] = Query(None),
    facility_id: Optional[UUID] = Query(None),
    tenant_id: UUID = Query(...),
    user: TokenPayload = Depends(get_current_user),
):
    results = []
    for e in _encounters.values():
        if e.tenant_id != tenant_id:
            continue
        if patient_id and e.patient_id != patient_id:
            continue
        if facility_id and e.facility_id != facility_id:
            continue
        results.append(_to_response(e))
    return results


@router.get("/{encounter_id}")
async def get_encounter(
    encounter_id: UUID,
    user: TokenPayload = Depends(get_current_user),
):
    encounter = _encounters.get(str(encounter_id))
    if not encounter:
        raise HTTPException(status_code=404, detail="Encounter not found")

    audit_emitter.emit(
        tenant_id=encounter.tenant_id,
        actor_id=safe_uuid(user.user_id),
        actor_type="staff",
        actor_role=user.role,
        action="read",
        resource_type="encounter",
        resource_id=encounter.id,
        outcome="success",
    )

    return _to_response(encounter)


@router.put("/{encounter_id}/status")
async def update_encounter_status(
    encounter_id: UUID,
    body: EncounterStatusUpdate,
    user: TokenPayload = Depends(get_current_user),
):
    encounter = _encounters.get(str(encounter_id))
    if not encounter:
        raise HTTPException(status_code=404, detail="Encounter not found")

    allowed = VALID_TRANSITIONS.get(encounter.status, ())
    if body.status not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid transition: {encounter.status} → {body.status}. Allowed: {allowed}",
        )

    old_status = encounter.status
    now = datetime.now(timezone.utc)
    encounter.status = body.status
    encounter.version += 1
    encounter.updated_at = now

    if body.status == "in_progress":
        encounter.started_at = now
    elif body.status == "draft":
        encounter.draft_at = now
    elif body.status == "signed":
        encounter.signed_at = now

    audit_emitter.emit(
        tenant_id=encounter.tenant_id,
        actor_id=safe_uuid(user.user_id),
        actor_type="staff",
        actor_role=user.role,
        action="status_change",
        resource_type="encounter",
        resource_id=encounter.id,
        outcome="success",
        audit_metadata={"old_status": old_status, "new_status": body.status},
    )

    return _to_response(encounter)
