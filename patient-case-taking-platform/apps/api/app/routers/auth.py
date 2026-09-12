"""Authentication, session management, and audit-linked endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.audit.emitter import audit_emitter, safe_uuid
from app.auth.dependencies import get_current_user
from app.auth.token import TokenPayload, create_dev_token, revoke_token, rotate_token
from app.models.device import deactivate_device, register_device
from app.sessions.state_machine import SessionType, session_manager

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/token")
async def create_token(
    user_id: str = Query(...),
    email: str = Query(...),
    role: str = Query(...),
    tenant_id: str = Query(...),
    facility_ids: list[str] = Query(...),
):
    """Create a dev auth token. In production, Clerk handles this."""
    token = create_dev_token(user_id, email, role, tenant_id, facility_ids)
    return {"token": token, "token_type": "bearer"}


@router.post("/token/rotate")
async def rotate_my_token(
    new_role: str | None = Query(None),
    user: TokenPayload = Depends(get_current_user),
    authorization: str = Header(...),
):
    """Replace the current credential without changing its role. Revoke the old token."""
    if new_role is not None and new_role != user.role:
        raise HTTPException(status_code=403, detail="Token rotation cannot change clinical role")
    token = rotate_token(authorization.partition(" ")[2].strip())
    if token is None:
        raise HTTPException(status_code=401, detail="Session is no longer valid")
    audit_emitter.emit(
        tenant_id=safe_uuid(user.tenant_id) or UUID(int=0),
        actor_id=safe_uuid(user.user_id),
        actor_type="staff",
        actor_role=user.role,
        action="token_rotate",
        resource_type="auth",
        resource_id=None,
        outcome="success",
        audit_metadata={"old_role": user.role, "new_role": new_role or user.role},
    )
    return {"token": token, "token_type": "bearer"}


@router.post("/revoke")
async def revoke_my_token(
    user: TokenPayload = Depends(get_current_user), authorization: str = Header(...),
):
    """Revoke current token."""
    revoke_token(authorization.partition(" ")[2].strip())
    audit_emitter.emit(
        tenant_id=safe_uuid(user.tenant_id) or UUID(int=0),
        actor_id=safe_uuid(user.user_id),
        actor_type="staff",
        actor_role=user.role,
        action="token_revoke",
        resource_type="auth",
        resource_id=None,
        outcome="success",
    )
    return {"status": "revoked"}


@router.post("/kiosk/session")
async def create_kiosk_session(
    facility_id: UUID = Query(...),
    device_id: str | None = Query(None),
    language: str = Query("hi"),
):
    """Create a new kiosk intake session."""
    session = session_manager.create_session(
        SessionType.KIOSK, facility_id, device_id, language
    )
    return {
        "session_id": str(session.session_id),
        "state": session.state,
        "expires_at": session.expires_at,
        "language": session.language,
    }


@router.post("/kiosk/session/{session_id}/touch")
async def touch_kiosk_session(session_id: UUID):
    """Update session activity. Returns 410 if expired."""
    session = session_manager.touch(session_id)
    if not session:
        raise HTTPException(status_code=410, detail="Session expired")
    return {"session_id": str(session.session_id), "state": session.state}


@router.post("/kiosk/session/{session_id}/expire")
async def expire_kiosk_session(session_id: UUID):
    """Manually expire and wipe a session."""
    session = session_manager.wipe_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "wiped"}


@router.post("/devices")
async def register_new_device(
    device_id: str = Query(...),
    facility_id: UUID = Query(...),
    device_type: str = Query(...),
    device_name: str = Query(...),
):
    """Register a kiosk/tablet device."""
    device = register_device(device_id, facility_id, device_type, device_name)
    return {"device_id": device.device_id, "is_active": device.is_active}


@router.post("/devices/{device_id}/deactivate")
async def deactivate_my_device(device_id: str):
    """Deactivate a device."""
    success = deactivate_device(device_id)
    if not success:
        raise HTTPException(status_code=404, detail="Device not found")
    return {"status": "deactivated"}
