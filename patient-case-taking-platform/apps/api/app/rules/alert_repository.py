"""Tenant-scoped durable alert projection, immutable history and transactional outbox."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.rules.alert_lifecycle import (
    AlertActor,
    AlertCommand,
    AlertConflict,
    AlertLifecycle,
    transition_alert,
)
from app.rules.engine import RuleResult


class AlertNotFound(LookupError):
    pass


class AlertEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    input_version: int = Field(ge=1)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


def _decode(value):
    return json.loads(value) if isinstance(value, str) else value


def _hash(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class PostgresAlertRepository:
    def __init__(self, pool: Any):
        self.pool = pool

    @staticmethod
    def _scope(actor: AlertActor, facility_id: UUID | None = None):
        if actor.role not in {"nurse", "doctor", "alert_worker"} or not actor.facility_ids:
            raise PermissionError("Clinical alert scope required")
        if facility_id is not None and facility_id not in actor.facility_ids:
            raise PermissionError("Facility access denied")

    async def raise_flag(
        self,
        *,
        actor: AlertActor,
        facility_id: UUID,
        encounter_id: UUID,
        evidence: AlertEvidence,
        rule: RuleResult,
        protected_evidence: dict | None = None,
        connection: Any = None,
    ) -> AlertLifecycle:
        """Accept only a server-evaluated rule and authoritative confirmed input evidence."""
        if actor.role == "patient":
            if facility_id not in actor.facility_ids or not protected_evidence:
                raise PermissionError("Confirmed patient evidence and facility scope required")
        else:
            self._scope(actor, facility_id)
        if connection is None:
            async with self.pool.acquire() as owned:
                async with owned.transaction():
                    await self._tenant(owned, actor.tenant_id)
                    return await self.raise_flag(
                        actor=actor,
                        facility_id=facility_id,
                        encounter_id=encounter_id,
                        evidence=evidence,
                        rule=rule,
                        protected_evidence=protected_evidence,
                        connection=owned,
                    )
        if not rule.triggered or not rule.evidence_paths or not rule.ruleset_version:
            raise ValueError("A triggered versioned rule with evidence is required")
        now = datetime.now(UTC)
        flag = AlertLifecycle(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            facility_id=facility_id,
            encounter_id=encounter_id,
            owner_role="doctor" if rule.owner_role == "doctor" else "nurse",
            updated_at=now,
        )
        metadata = {
            "rule_id": rule.rule_id,
            "rule_version": rule.rule_version,
            "ruleset_version": rule.ruleset_version,
            "severity": rule.severity.value,
            "explanation_code": rule.explanation_code,
            "evidence_paths": list(rule.evidence_paths),
            "approval_status": rule.approval_status,
        }
        row = await connection.fetchrow(
            "INSERT INTO triage_flag (id,tenant_id,facility_id,encounter_id,input_version,rule_id,rule_version,ruleset_version,evidence_fingerprint,rule_metadata,lifecycle,version) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::JSONB,$11::JSONB,1) ON CONFLICT DO NOTHING RETURNING id",
            flag.id,
            actor.tenant_id,
            facility_id,
            encounter_id,
            evidence.input_version,
            rule.rule_id,
            rule.rule_version,
            rule.ruleset_version,
            evidence.fingerprint,
            json.dumps(metadata),
            flag.model_dump_json(),
        )
        if row is None:
            existing = await connection.fetchval(
                "SELECT lifecycle FROM triage_flag WHERE tenant_id=$1 AND facility_id=$2 AND encounter_id=$3 AND input_version=$4 "
                "AND rule_id=$5 AND rule_version=$6 AND ruleset_version=$7 AND evidence_fingerprint=$8",
                actor.tenant_id,
                facility_id,
                encounter_id,
                evidence.input_version,
                rule.rule_id,
                rule.rule_version,
                rule.ruleset_version,
                evidence.fingerprint,
            )
            return AlertLifecycle.model_validate(_decode(existing))
        await self._record(
            connection,
            flag,
            actor,
            "raised",
            "raised",
            _hash(metadata),
            protected_evidence or {},
            metadata,
        )
        return flag

    async def list_flags(
        self, actor: AlertActor, *, limit: int = 100, include_closed: bool = False
    ) -> list[dict]:
        self._scope(actor)
        if not 1 <= limit <= 200:
            raise ValueError("Limit must be between 1 and 200")
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await self._tenant(connection, actor.tenant_id)
                rows = await connection.fetch(
                    "SELECT lifecycle,rule_metadata, CASE "
                    "WHEN EXISTS (SELECT 1 FROM triage_outbox o WHERE o.flag_id=triage_flag.id AND o.dead_lettered_at IS NOT NULL) THEN 'failed' "
                    "WHEN EXISTS (SELECT 1 FROM triage_outbox o WHERE o.flag_id=triage_flag.id AND o.published_at IS NULL) THEN 'pending' "
                    "ELSE 'broker_published' END AS delivery FROM triage_flag WHERE tenant_id=$1 AND facility_id=ANY($2::UUID[]) "
                    "AND ($4::BOOLEAN OR lifecycle->>'state' NOT IN ('resolved','overridden')) "
                    "ORDER BY CASE rule_metadata->>'severity' WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END, created_at,id LIMIT $3",
                    actor.tenant_id,
                    list(actor.facility_ids),
                    limit,
                    include_closed,
                )
        return [
            {
                "lifecycle": _decode(row["lifecycle"]),
                "rule": _decode(row["rule_metadata"]),
                "delivery": row["delivery"],
            }
            for row in rows
        ]

    async def command(
        self,
        *,
        flag_id: UUID,
        actor: AlertActor,
        command: AlertCommand,
        idempotency_key: str,
        target: AlertActor | None = None,
        escalation_role: str | None = None,
        timer_policy_fingerprint: str | None = None,
    ) -> AlertLifecycle:
        self._scope(actor)
        if not idempotency_key.strip() or len(idempotency_key) > 128:
            raise ValueError("Bounded idempotency key required")
        digest = _hash(
            {
                "actor": {
                    **actor.model_dump(mode="json"),
                    "facility_ids": sorted(str(value) for value in actor.facility_ids),
                },
                "command": command.model_dump(mode="json"),
                "target": {
                    **target.model_dump(mode="json"),
                    "facility_ids": sorted(str(value) for value in target.facility_ids),
                }
                if target
                else None,
                "escalation_role": escalation_role,
                **({"timer_policy_fingerprint": timer_policy_fingerprint} if timer_policy_fingerprint else {}),
            }
        )
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await self._tenant(connection, actor.tenant_id)
                if command.action.value == "escalate":
                    active = await connection.fetchrow(
                        "SELECT a.fingerprint,p.document->>'worker_actor_id' AS worker_actor_id "
                        "FROM triage_active_policy a JOIN triage_policy_artifact p "
                        "ON (a.tenant_id,a.facility_id,a.fingerprint)=(p.tenant_id,p.facility_id,p.fingerprint) "
                        "WHERE a.tenant_id=$1 AND a.facility_id=ANY($2::UUID[]) FOR SHARE OF a",
                        actor.tenant_id, list(actor.facility_ids),
                    )
                    if (
                        len(actor.facility_ids) != 1 or active is None
                        or active["fingerprint"] != timer_policy_fingerprint
                        or active["worker_actor_id"] != str(actor.actor_id)
                    ):
                        raise AlertConflict("Timer policy is inactive or worker scope changed")
                row = await connection.fetchrow(
                    "SELECT lifecycle,rule_metadata FROM triage_flag WHERE tenant_id=$1 AND id=$2 "
                    "AND facility_id=ANY($3::UUID[]) FOR UPDATE",
                    actor.tenant_id,
                    flag_id,
                    list(actor.facility_ids),
                )
                if row is None:
                    raise AlertNotFound("Alert not found")
                replay = await connection.fetchrow(
                    "SELECT request_hash,result FROM triage_flag_history WHERE tenant_id=$1 AND flag_id=$2 AND idempotency_key=$3",
                    actor.tenant_id,
                    flag_id,
                    idempotency_key,
                )
                if replay is not None:
                    if replay["request_hash"] != digest:
                        raise AlertConflict("Idempotency key was used for a different command")
                    return AlertLifecycle.model_validate(_decode(replay["result"]))
                current = AlertLifecycle.model_validate(_decode(row["lifecycle"]))
                transition = transition_alert(
                    current,
                    command,
                    actor,
                    now=datetime.now(UTC),
                    target=target,
                    escalation_role=escalation_role,
                )
                result = transition.resulting
                await connection.execute(
                    "UPDATE triage_flag SET lifecycle=$3::JSONB,version=$4 WHERE tenant_id=$1 AND id=$2",
                    actor.tenant_id,
                    flag_id,
                    result.model_dump_json(),
                    result.version,
                )
                await self._record(
                    connection,
                    result,
                    actor,
                    command.action.value,
                    idempotency_key,
                    digest,
                    transition.model_dump(mode="json", exclude={"resulting"}),
                    _decode(row["rule_metadata"]),
                )
        return result

    @staticmethod
    async def _tenant(connection, tenant_id):
        await connection.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_id))

    @staticmethod
    async def _record(connection, flag, actor, action, key, digest, protected, rule):
        await connection.execute(
            "INSERT INTO triage_flag_history (id,tenant_id,flag_id,version,actor_id,idempotency_key,request_hash,action,protected_detail,result) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::JSONB,$10::JSONB)",
            uuid4(),
            actor.tenant_id,
            flag.id,
            flag.version,
            actor.actor_id,
            key,
            digest,
            action,
            json.dumps(protected),
            flag.model_dump_json(),
        )
        event_type = {
            "raised": "CriticalAlertRaised.v1",
            "acknowledge": "CriticalAlertAcknowledged.v1",
            "handoff": "CriticalAlertHandoffRequested.v1",
            "escalate": "CriticalAlertEscalated.v1",
            "resolve": "CriticalAlertResolved.v1",
            "override": "CriticalAlertOverridden.v1",
        }[action]
        payload = {
            "flag_id": str(flag.id),
            "facility_id": str(flag.facility_id),
            "encounter_id": str(flag.encounter_id),
            "version": flag.version,
            "state": flag.state.value,
            "actor_id": str(actor.actor_id),
            "rule_id": rule["rule_id"],
            "rule_version": rule["rule_version"],
            "ruleset_version": rule["ruleset_version"],
        }
        await connection.execute(
            "INSERT INTO triage_outbox (id,tenant_id,flag_id,flag_version,event_type,payload) VALUES ($1,$2,$3,$4,$5,$6::JSONB)",
            uuid4(),
            actor.tenant_id,
            flag.id,
            flag.version,
            event_type,
            json.dumps(payload),
        )
