"""Bind speech processing to authenticated patients and durable treatment consent."""

import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException

from app.auth.service import authenticate_token
from app.database import get_postgres_pool
from app.patient_portal.service import PatientIdentity
from app.patient_portal.sessions import (
    IntakeSessionRepository,
    IntakeSessionUnavailable,
    session_owner,
)


async def authorize_voice(
    token: str,
    tenant_id: UUID,
    encounter_id: UUID,
    consent_id: UUID,
    retain_audio: bool = False,
    *,
    session_id: UUID,
) -> UUID:
    user = await authenticate_token(token)
    try:
        patient_id = UUID(user.user_id)
        allowed = user.role == "patient" and UUID(user.tenant_id) == tenant_id
    except (ValueError, TypeError):
        allowed = False
    if not allowed or not user.facility_ids:
        raise HTTPException(403, "Patient voice access denied")
    try:
        identity = PatientIdentity(tenant_id, patient_id, {UUID(value) for value in user.facility_ids})
    except (ValueError, TypeError) as exc:
        raise HTTPException(403, "Patient voice access denied") from exc
    pool = await get_postgres_pool()
    try:
        session = await IntakeSessionRepository(pool).access(identity, session_owner(user), session_id)
    except IntakeSessionUnavailable as exc:
        raise HTTPException(403, "Active patient intake session required") from exc
    if session["encounter_id"] != encounter_id:
        raise HTTPException(403, "Active patient intake session required")
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_id))
            row = await connection.fetchrow(
                "SELECT patient_id, encounter_id, purpose, status, scope, expires_at "
                "FROM consent_artifact WHERE tenant_id = $1 AND id = $2",
                tenant_id,
                consent_id,
            )
    if row is None:
        raise HTTPException(403, "Active treatment consent required")
    scope = row["scope"] or {}
    if isinstance(scope, str):
        try:
            scope = json.loads(scope)
        except (ValueError, TypeError):
            scope = {}
    if (
        row["patient_id"] != patient_id
        or row["encounter_id"] != encounter_id
        or row["purpose"] != "treatment"
        or row["status"] != "granted"
        or (row["expires_at"] is not None and row["expires_at"] <= datetime.now(UTC))
        or (
            retain_audio
            and (not isinstance(scope, dict) or scope.get("audio_retention") is not True)
        )
    ):
        raise HTTPException(403, "Active treatment consent required")
    return patient_id
