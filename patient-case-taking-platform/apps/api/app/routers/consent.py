"""Consent endpoints with audit trail.
Every consent grant/revoke/check emits an immutable audit event."""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.audit.emitter import audit_emitter, safe_uuid
from app.auth.dependencies import get_current_user
from app.auth.token import TokenPayload
from app.models.consent_artifact import ConsentArtifact
from app.schemas.consent import ConsentCreate, ConsentRevoke

router = APIRouter(prefix="/api/v1/consents", tags=["consents"])

_consents: dict[str, ConsentArtifact] = {}


def _to_response(c: ConsentArtifact) -> dict:
    return {
        "id": c.id,
        "tenant_id": c.tenant_id,
        "patient_id": c.patient_id,
        "encounter_id": c.encounter_id,
        "purpose": c.purpose,
        "scope": c.scope,
        "status": c.status,
        "granted_at": c.granted_at,
        "expires_at": c.expires_at,
        "revoked_at": c.revoked_at,
        "revoke_reason": c.revoke_reason,
        "granted_by": c.granted_by,
        "version": c.version,
    }


@router.post("", status_code=201)
async def create_consent(
    body: ConsentCreate,
    tenant_id: UUID = Query(...),
    user: TokenPayload = Depends(get_current_user),
):
    consent = ConsentArtifact(
        tenant_id=tenant_id,
        patient_id=body.patient_id,
        encounter_id=body.encounter_id,
        purpose=body.purpose,
        scope=body.scope,
        granted_by=body.granted_by,
        expires_at=body.expires_at,
    )
    _consents[str(consent.id)] = consent

    # Emit audit event
    audit_emitter.emit(
        tenant_id=tenant_id,
        actor_id=safe_uuid(user.user_id),
        actor_type="patient" if body.granted_by == "patient" else "staff",
        actor_role=user.role,
        action="grant_consent",
        resource_type="consent",
        resource_id=consent.id,
        purpose=body.purpose,
        outcome="success",
        audit_metadata={"scope": body.scope, "expires_at": str(body.expires_at)},
    )

    return _to_response(consent)


@router.get("/{consent_id}")
async def get_consent(
    consent_id: UUID,
    user: TokenPayload = Depends(get_current_user),
):
    consent = _consents.get(str(consent_id))
    if not consent:
        raise HTTPException(status_code=404, detail="Consent not found")

    # Audit the read
    audit_emitter.emit(
        tenant_id=consent.tenant_id,
        actor_id=safe_uuid(user.user_id),
        actor_type="staff",
        actor_role=user.role,
        action="read",
        resource_type="consent",
        resource_id=consent.id,
        outcome="success",
    )

    return _to_response(consent)


@router.get("")
async def list_consents(
    patient_id: Optional[UUID] = Query(None),
    tenant_id: UUID = Query(...),
    user: TokenPayload = Depends(get_current_user),
):
    results = [
        _to_response(c)
        for c in _consents.values()
        if c.tenant_id == tenant_id and (patient_id is None or c.patient_id == patient_id)
    ]
    return results


@router.post("/{consent_id}/revoke")
async def revoke_consent(
    consent_id: UUID,
    body: ConsentRevoke,
    user: TokenPayload = Depends(get_current_user),
):
    consent = _consents.get(str(consent_id))
    if not consent:
        raise HTTPException(status_code=404, detail="Consent not found")
    if consent.status != "granted":
        raise HTTPException(status_code=409, detail=f"Cannot revoke consent in status '{consent.status}'")

    # Create new revoked version
    revoked = ConsentArtifact(
        tenant_id=consent.tenant_id,
        patient_id=consent.patient_id,
        encounter_id=consent.encounter_id,
        purpose=consent.purpose,
        scope=consent.scope,
        granted_by=consent.granted_by,
        status="revoked",
        granted_at=consent.granted_at,
        revoked_at=datetime.now(timezone.utc),
        revoke_reason=body.reason,
        previous_version_id=consent.id,
        version=consent.version + 1,
    )
    consent.status = "revoked"
    _consents[str(revoked.id)] = revoked

    # Emit audit event
    audit_emitter.emit(
        tenant_id=consent.tenant_id,
        actor_id=safe_uuid(user.user_id),
        actor_type="staff",
        actor_role=user.role,
        action="revoke_consent",
        resource_type="consent",
        resource_id=consent.id,
        outcome="success",
        audit_metadata={"reason": body.reason, "new_version": str(revoked.id)},
    )

    return _to_response(revoked)


@router.post("/{consent_id}/check")
async def check_consent(
    consent_id: UUID,
    purpose: str = Query(...),
    user: TokenPayload = Depends(get_current_user),
):
    consent = _consents.get(str(consent_id))
    if not consent:
        raise HTTPException(status_code=404, detail="Consent not found")

    valid = True
    reason = None

    if consent.status != "granted":
        valid = False
        reason = f"Consent status is '{consent.status}'"
    elif consent.expires_at and consent.expires_at < datetime.now(timezone.utc):
        valid = False
        reason = "Consent has expired"
    elif consent.purpose != purpose and consent.purpose != "emergency":
        valid = False
        reason = f"Consent purpose '{consent.purpose}' does not match requested '{purpose}'"

    # Audit the check
    audit_emitter.emit(
        tenant_id=consent.tenant_id,
        actor_id=safe_uuid(user.user_id),
        actor_type="staff",
        actor_role=user.role,
        action="check_consent",
        resource_type="consent",
        resource_id=consent.id,
        purpose=purpose,
        outcome="success" if valid else "denied",
        outcome_detail=reason,
    )

    return {"valid": valid, "reason": reason}
