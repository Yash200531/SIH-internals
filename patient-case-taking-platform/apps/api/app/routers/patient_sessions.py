"""Authenticated patient intake session creation and lifecycle."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from app.auth.dependencies import get_current_user
from app.auth.token import TokenPayload
from app.database import get_postgres_pool
from app.patient_portal.sessions import (
    IntakeSessionRepository,
    IntakeSessionUnavailable,
    session_owner,
)
from app.routers.patient_portal import patient_identity

router = APIRouter(prefix="/api/v1/patient-portal/me/sessions", tags=["patient-sessions"])


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facility_id: UUID
    language: Literal["hi", "en"]


async def repository():
    return IntakeSessionRepository(await get_postgres_pool())


@router.post("")
async def create(command: SessionCreate, response: Response, idempotency_key: UUID = Header(...),
                 user: TokenPayload = Depends(get_current_user), repo=Depends(repository)):
    identity = patient_identity(user)
    if command.facility_id not in identity.facility_ids:
        raise HTTPException(403, "Facility access denied")
    try:
        result = await repo.create(identity, session_owner(user), command.facility_id, command.language, idempotency_key)
    except IntakeSessionUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post("/{session_id}/touch")
async def touch(session_id: UUID, response: Response, user: TokenPayload = Depends(get_current_user), repo=Depends(repository)):
    try:
        result = await repo.access(patient_identity(user), session_owner(user), session_id, touch=True)
    except IntakeSessionUnavailable as exc:
        raise HTTPException(404, "Active patient intake session not found") from exc
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post("/{session_id}/end")
async def end(session_id: UUID, response: Response, user: TokenPayload = Depends(get_current_user), repo=Depends(repository)):
    try:
        await repo.access(patient_identity(user), session_owner(user), session_id, end=True)
    except IntakeSessionUnavailable as exc:
        raise HTTPException(404, "Active patient intake session not found") from exc
    response.headers["Cache-Control"] = "private, no-store"
    return {"status": "ended"}
