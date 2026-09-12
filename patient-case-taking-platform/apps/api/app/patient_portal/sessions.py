"""Server-owned, expiring intake sessions scoped to one authenticated session."""

import hashlib
import json
from typing import Any, Literal
from uuid import UUID, uuid4

from app.auth.token import TokenPayload
from app.patient_portal.service import PatientIdentity


class IntakeSessionUnavailable(ValueError):
    pass


def session_owner(user: TokenPayload) -> str:
    # Stable over provider token refresh, different across applications/sessions.
    key = (user.external_issuer, user.external_audience, user.external_subject,
           user.session_id or user.token_hash)
    return hashlib.sha256(json.dumps(key, separators=(",", ":")).encode()).hexdigest()


class IntakeSessionRepository:
    def __init__(self, pool: Any):
        self.pool = pool

    @staticmethod
    async def scope(connection, identity: PatientIdentity):
        await connection.execute(
            "SELECT set_config('app.tenant_id',$1,true),set_config('app.patient_id',$2,true)",
            str(identity.tenant_id), str(identity.patient_id),
        )

    @staticmethod
    def public(row):
        return {key: row[key] for key in ("id", "encounter_id", "facility_id", "language", "expires_at", "hard_expires_at")}

    async def create(self, identity: PatientIdentity, owner: str, facility_id: UUID,
                     language: Literal["hi", "en"], idempotency_key: UUID):
        if facility_id not in identity.facility_ids:
            raise IntakeSessionUnavailable("Facility access denied")
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await self.scope(connection, identity)
                inserted = await connection.fetchval(
                    "INSERT INTO patient_intake_session(id,tenant_id,patient_id,facility_id,encounter_id,owner_session_hash,idempotency_key,language) "
                    "VALUES($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT(tenant_id,patient_id,owner_session_hash,idempotency_key) DO NOTHING RETURNING id",
                    uuid4(), identity.tenant_id, identity.patient_id, facility_id, uuid4(), owner, idempotency_key, language,
                )
                row = await connection.fetchrow(
                    "SELECT * FROM patient_intake_session WHERE tenant_id=$1 AND patient_id=$2 AND owner_session_hash=$3 AND idempotency_key=$4 "
                    "AND ended_at IS NULL AND expires_at>CURRENT_TIMESTAMP AND hard_expires_at>CURRENT_TIMESTAMP",
                    identity.tenant_id, identity.patient_id, owner, idempotency_key,
                )
                if row is None or row["facility_id"] != facility_id or row["language"] != language:
                    raise IntakeSessionUnavailable("Session expired or request key was reused with different input")
                if inserted:
                    await self.history(connection, identity, inserted, "created")
                return self.public(row)

    @staticmethod
    async def history(connection, identity, session_id, action):
        await connection.execute(
            "INSERT INTO patient_intake_session_history(id,tenant_id,patient_id,session_id,action) VALUES($1,$2,$3,$4,$5)",
            uuid4(), identity.tenant_id, identity.patient_id, session_id, action,
        )

    async def access(self, identity: PatientIdentity, owner: str, session_id: UUID, *, touch=False, end=False):
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await self.scope(connection, identity)
                row = await connection.fetchrow(
                    "SELECT * FROM patient_intake_session WHERE id=$1 AND tenant_id=$2 AND patient_id=$3 AND owner_session_hash=$4 "
                    "AND facility_id=ANY($5::UUID[]) AND ended_at IS NULL AND expires_at>CURRENT_TIMESTAMP AND hard_expires_at>CURRENT_TIMESTAMP FOR UPDATE",
                    session_id, identity.tenant_id, identity.patient_id, owner, list(identity.facility_ids),
                )
                if row is None:
                    raise IntakeSessionUnavailable("Active patient intake session required")
                if end:
                    await connection.execute("UPDATE patient_intake_session SET ended_at=CURRENT_TIMESTAMP WHERE id=$1", session_id)
                    await self.history(connection, identity, session_id, "ended")
                elif touch:
                    row = await connection.fetchrow(
                        "UPDATE patient_intake_session SET last_seen_at=CURRENT_TIMESTAMP,expires_at=LEAST(hard_expires_at,CURRENT_TIMESTAMP+INTERVAL '5 minutes') WHERE id=$1 RETURNING *", session_id,
                    )
                return self.public(row)
