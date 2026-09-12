from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.models.intake_session import IntakeSession
from app.schemas.intake_session import IntakeSessionCreate

router = APIRouter(prefix="/api/v1/sessions", tags=["intake-sessions"])

_sessions: dict[str, IntakeSession] = {}

SESSION_TTL_MINUTES = 60


def _to_response(s: IntakeSession) -> dict:
    return {
        "id": s.id,
        "facility_id": s.facility_id,
        "session_type": s.session_type,
        "status": s.status,
        "language": s.language,
        "expires_at": s.expires_at,
        "created_at": s.created_at,
    }


@router.post("", status_code=201)
async def create_session(body: IntakeSessionCreate, tenant_id: UUID = Query(...)):
    now = datetime.now(timezone.utc)
    session = IntakeSession(
        tenant_id=tenant_id,
        facility_id=body.facility_id,
        session_type=body.session_type,
        device_id=body.device_id,
        language=body.language,
        expires_at=now + timedelta(minutes=SESSION_TTL_MINUTES),
        last_activity_at=now,
    )
    _sessions[str(session.id)] = session
    return _to_response(session)


@router.get("/{session_id}")
async def get_session(session_id: UUID):
    session = _sessions.get(str(session_id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    now = datetime.now(timezone.utc)
    if session.status == "active" and now > session.expires_at:
        session.status = "expired"
    return _to_response(session)


@router.post("/{session_id}/expire")
async def expire_session(session_id: UUID):
    session = _sessions.get(str(session_id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    now = datetime.now(timezone.utc)
    session.status = "expired"
    session.wiped_at = now
    session.updated_at = now
    return _to_response(session)


@router.post("/{session_id}/link-patient")
async def link_patient(session_id: UUID, patient_id: UUID = Query(...)):
    session = _sessions.get(str(session_id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "active":
        raise HTTPException(status_code=422, detail="Session is not active")
    now = datetime.now(timezone.utc)
    if now > session.expires_at:
        session.status = "expired"
        raise HTTPException(status_code=422, detail="Session has expired")
    session.patient_id = patient_id
    session.last_activity_at = now
    session.version += 1
    return _to_response(session)
