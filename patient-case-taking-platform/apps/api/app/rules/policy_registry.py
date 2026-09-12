"""Operator-managed active facility policy and immutable activation evidence."""

import re
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from app.rules.alert_lifecycle import AlertConflict

if TYPE_CHECKING:
    from app.rules.alert_timers import FacilityEscalationPolicy


class PolicyRegistry:
    def __init__(self, pool: Any):
        self.pool = pool

    async def status(self, tenant_id: UUID, facility_id: UUID) -> dict:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT set_config('app.tenant_id',$1,true)", str(tenant_id))
                row = await connection.fetchrow(
                    "SELECT fingerprint,revision FROM triage_active_policy WHERE tenant_id=$1 AND facility_id=$2",
                    tenant_id, facility_id,
                )
        return dict(row) if row else {"fingerprint": None, "revision": 0}

    async def set_active(
        self, policy: "FacilityEscalationPolicy", *, operator_id: UUID,
        reason_code: str, expected_revision: int, enabled: bool = True,
    ) -> int:
        if expected_revision < 0 or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", reason_code) is None:
            raise ValueError("Nonnegative revision and controlled reason code required")
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT set_config('app.tenant_id',$1,true)", str(policy.tenant_id))
                # Serialize even first activation, when there is no row to lock.
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                    f"triage-policy:{policy.tenant_id}:{policy.facility_id}",
                )
                row = await connection.fetchrow(
                    "SELECT fingerprint,revision FROM triage_active_policy WHERE tenant_id=$1 AND facility_id=$2 FOR UPDATE",
                    policy.tenant_id, policy.facility_id,
                )
                revision = row["revision"] if row else 0
                if expected_revision != revision:
                    raise AlertConflict("Active policy revision is stale")
                fingerprint = policy.fingerprint if enabled else None
                if row and row["fingerprint"] == fingerprint:
                    return revision
                if enabled:
                    await connection.execute(
                        "INSERT INTO triage_policy_artifact (tenant_id,facility_id,fingerprint,policy_id,policy_version,document) "
                        "VALUES ($1,$2,$3,$4,$5,$6::JSONB) ON CONFLICT DO NOTHING",
                        policy.tenant_id, policy.facility_id, fingerprint,
                        policy.policy_id, policy.version, policy.model_dump_json(),
                    )
                    stored = await connection.fetchval(
                        "SELECT fingerprint FROM triage_policy_artifact WHERE tenant_id=$1 AND facility_id=$2 AND policy_id=$3 AND policy_version=$4",
                        policy.tenant_id, policy.facility_id, policy.policy_id, policy.version,
                    )
                    if stored != fingerprint:
                        raise AlertConflict("Policy version already exists with different content")
                revision += 1
                await connection.execute(
                    "INSERT INTO triage_active_policy (tenant_id,facility_id,fingerprint,revision) VALUES ($1,$2,$3,$4) "
                    "ON CONFLICT (tenant_id,facility_id) DO UPDATE SET fingerprint=EXCLUDED.fingerprint,revision=EXCLUDED.revision",
                    policy.tenant_id, policy.facility_id, fingerprint, revision,
                )
                await connection.execute(
                    "INSERT INTO triage_policy_activation_history (id,tenant_id,facility_id,revision,fingerprint,operator_id,reason_code) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7)",
                    uuid4(), policy.tenant_id, policy.facility_id, revision, fingerprint, operator_id, reason_code,
                )
        return revision
