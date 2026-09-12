"""Internal identity grants are separate from verified external session claims."""

import hashlib
import re
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.auth.jwt_verifier import VerifiedSession
from app.auth.token import TokenPayload


class IdentityBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str = Field(min_length=1, max_length=255)
    audience: str = Field(min_length=1, max_length=128)
    subject: str = Field(min_length=1, max_length=128)
    internal_id: UUID
    tenant_id: UUID
    role: Literal["patient", "doctor", "nurse", "admin", "receptionist", "kiosk_operator", "caregiver"]
    facility_ids: tuple[UUID, ...] = Field(min_length=1, max_length=50)
    active: bool = True


class IdentityGrantConflict(ValueError):
    pass


class IdentityRepository:
    def __init__(self, pool: Any):
        self.pool = pool

    @staticmethod
    async def scope(connection, issuer, audience, subject):
        await connection.execute(
            "SELECT set_config('app.auth_issuer',$1,true),set_config('app.auth_audience',$2,true),set_config('app.auth_subject',$3,true)",
            issuer, audience, subject,
        )

    async def grant(self, binding: IdentityBinding, *, operator_id: UUID, reason_code: str, expected_version: int) -> int:
        if expected_version < 0 or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", reason_code) is None:
            raise ValueError("Expected version and controlled grant reason required")
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await self.scope(connection, binding.issuer, binding.audience, binding.subject)
                await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"identity:{binding.issuer}:{binding.audience}:{binding.subject}")
                row = await connection.fetchrow(
                    "SELECT internal_id,tenant_id,version FROM auth_identity_binding WHERE issuer=$1 AND audience=$2 AND subject=$3 FOR UPDATE",
                    binding.issuer, binding.audience, binding.subject,
                )
                current = row["version"] if row else 0
                if current != expected_version:
                    raise IdentityGrantConflict("Identity grant version is stale")
                if row and (row["internal_id"] != binding.internal_id or row["tenant_id"] != binding.tenant_id):
                    raise IdentityGrantConflict("Identity relinking requires a separate governed migration")
                version = current + 1
                await connection.execute(
                    "INSERT INTO auth_identity_binding (issuer,audience,subject,internal_id,tenant_id,role,facility_ids,active,version) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT (issuer,audience,subject) DO UPDATE "
                    "SET role=EXCLUDED.role,facility_ids=EXCLUDED.facility_ids,active=EXCLUDED.active,version=EXCLUDED.version",
                    binding.issuer, binding.audience, binding.subject, binding.internal_id,
                    binding.tenant_id, binding.role, list(binding.facility_ids), binding.active, version,
                )
                await connection.execute(
                    "INSERT INTO auth_identity_history (id,issuer,audience,subject,version,operator_id,reason_code,binding) VALUES ($1,$2,$3,$4,$5,$6,$7,$8::JSONB)",
                    uuid4(), binding.issuer, binding.audience, binding.subject, version,
                    operator_id, reason_code, binding.model_dump_json(),
                )
        return version

    async def resolve(self, session: VerifiedSession, token: str) -> TokenPayload | None:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await self.scope(connection, session.issuer, session.audience, session.subject)
                row = await connection.fetchrow(
                    "SELECT internal_id,tenant_id,role,facility_ids FROM auth_identity_binding b "
                    "WHERE issuer=$1 AND audience=$2 AND subject=$3 AND active "
                    "AND NOT EXISTS (SELECT 1 FROM auth_revoked_session r WHERE (r.issuer,r.audience,r.subject)=(b.issuer,b.audience,b.subject) AND r.session_id=$4)",
                    session.issuer, session.audience, session.subject, session.session_id,
                )
        if row is None:
            return None
        return TokenPayload(
            user_id=str(row["internal_id"]), email=None, tenant_id=str(row["tenant_id"]), role=row["role"],
            facility_ids=[str(item) for item in row["facility_ids"]], issued_at=session.issued_at,
            expires_at=session.expires_at, token_hash=hashlib.sha256(token.encode()).hexdigest(),
            session_id=session.session_id, external_issuer=session.issuer,
            external_audience=session.audience, external_subject=session.subject,
        )

    async def revoke_session(self, user: TokenPayload):
        if not all((user.external_issuer, user.external_audience, user.external_subject, user.session_id)):
            raise ValueError("Verified external session required")
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await self.scope(connection, user.external_issuer, user.external_audience, user.external_subject)
                await connection.execute(
                    "INSERT INTO auth_revoked_session (issuer,audience,subject,session_id) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                    user.external_issuer, user.external_audience, user.external_subject, user.session_id,
                )
