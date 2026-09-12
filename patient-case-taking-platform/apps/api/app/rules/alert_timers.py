"""Facility-scoped prototype escalation ladder backed by durable alert history."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import asyncpg
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import settings
from app.rules.alert_lifecycle import (
    AlertAction,
    AlertActor,
    AlertCommand,
    AlertConflict,
    AlertLifecycle,
)
from app.rules.alert_repository import AlertNotFound, PostgresAlertRepository
from app.rules.policy_registry import PolicyRegistry


class EscalationStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    after_seconds: int = Field(ge=1, le=86400)
    owner_role: Literal["doctor"] = "doctor"


class FacilityEscalationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tenant_id: UUID
    facility_id: UUID
    worker_actor_id: UUID
    policy_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    version: str = Field(pattern=r"^[a-zA-Z0-9._-]{1,32}$")
    owner_reference: str = Field(min_length=1, max_length=128)
    approval_status: Literal["prototype_only"] = "prototype_only"
    steps: tuple[EscalationStep, ...] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def increasing_deadlines(self):
        deadlines = [step.after_seconds for step in self.steps]
        if any(right <= left for left, right in zip(deadlines, deadlines[1:])):
            raise ValueError("Escalation deadlines must strictly increase from alert creation")
        return self

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class AlertTimerWorker:
    def __init__(self, pool: Any, policy: FacilityEscalationPolicy):
        self.pool = pool
        self.policy = policy
        self.repository = PostgresAlertRepository(pool)
        self.actor = AlertActor(
            actor_id=policy.worker_actor_id, tenant_id=policy.tenant_id,
            facility_ids=frozenset({policy.facility_id}), role="alert_worker",
        )

    async def run_once(self, limit: int = 100) -> int:
        """Advance at most one due ladder step per alert; no in-memory timer state."""
        if not 1 <= limit <= 200:
            raise ValueError("Timer batch size must be between 1 and 200")
        active = await PolicyRegistry(self.pool).status(self.policy.tenant_id, self.policy.facility_id)
        if active["fingerprint"] != self.policy.fingerprint:
            return 0
        prefix = f"timer:{self.policy.fingerprint}:"
        steps = json.dumps([step.model_dump() for step in self.policy.steps])
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await self.repository._tenant(connection, self.policy.tenant_id)
                # Pick the first unfinished step, not just any overdue step. Completed
                # ladders and not-yet-due flags cannot starve due alerts in a batch.
                rows = await connection.fetch(
                    "SELECT f.lifecycle, s.ordinal::INTEGER AS step_index FROM triage_flag f "
                    "CROSS JOIN LATERAL (SELECT item,ordinal FROM "
                    "jsonb_array_elements($3::JSONB) WITH ORDINALITY AS ladder(item,ordinal) "
                    "WHERE NOT EXISTS (SELECT 1 FROM triage_flag_history h "
                    "WHERE h.tenant_id=f.tenant_id AND h.flag_id=f.id "
                    "AND h.idempotency_key=$4 || ordinal::TEXT) "
                    "ORDER BY ordinal LIMIT 1) s "
                    "WHERE f.tenant_id=$1 AND f.facility_id=$2 "
                    "AND f.lifecycle->>'state' IN ('open','escalated') "
                    "AND f.created_at <= now() - (s.item->>'after_seconds')::INTEGER * INTERVAL '1 second' "
                    "ORDER BY f.created_at,f.id LIMIT $5",
                    self.policy.tenant_id, self.policy.facility_id, steps, prefix, limit,
                )
        processed = 0
        for row in rows:
            flag = AlertLifecycle.model_validate_json(row["lifecycle"])
            step_index = row["step_index"]
            step = self.policy.steps[step_index - 1]
            try:
                await self.repository.command(
                    flag_id=flag.id, actor=self.actor,
                    command=AlertCommand(
                        action=AlertAction.ESCALATE, expected_version=flag.version,
                        reason_code="acknowledgement_timeout",
                        rationale=json.dumps({
                            "policy": self.policy.model_dump(mode="json"),
                            "policy_fingerprint": self.policy.fingerprint,
                            "step": step_index,
                        }, separators=(",", ":")),
                    ),
                    escalation_role=step.owner_role,
                    timer_policy_fingerprint=self.policy.fingerprint,
                    idempotency_key=f"{prefix}{step_index}",
                )
                processed += 1
            except (AlertConflict, AlertNotFound):
                # Acknowledgement or another timer won the version race. The next
                # database scan decides what remains due; never force a stale command.
                continue
        return processed


async def _run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("once", "forever", "status", "activate", "deactivate"))
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--operator-id", type=UUID)
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--reason-code")
    args = parser.parse_args()
    if not settings.TRIAGE_WORKFLOW_ENABLED or not settings.ENABLE_DEMO_ROUTES:
        raise RuntimeError("Prototype timer requires triage workflow and demo routes enabled")
    if args.policy.stat().st_size > 16384:
        raise ValueError("Policy file must be at most 16 KiB")
    policy = FacilityEscalationPolicy.model_validate_json(args.policy.read_text(encoding="utf-8"))
    changing = args.command in {"activate", "deactivate"}
    if changing and (
        not settings.DATABASE_MAINTENANCE_URL or args.operator_id is None
        or args.expected_revision is None or args.reason_code is None
    ):
        raise ValueError("Policy change requires maintenance DB, operator ID, expected revision and reason code")
    pool = await asyncpg.create_pool(
        settings.DATABASE_MAINTENANCE_URL if changing else settings.DATABASE_URL,
        min_size=1, max_size=2,
    )
    try:
        registry = PolicyRegistry(pool)
        if changing:
            revision = await registry.set_active(
                policy, operator_id=args.operator_id, reason_code=args.reason_code,
                expected_revision=args.expected_revision, enabled=args.command == "activate",
            )
            print(f"Policy revision={revision}")
            return
        if args.command == "status":
            print(json.dumps(await registry.status(policy.tenant_id, policy.facility_id)))
            return
        worker = AlertTimerWorker(pool, policy)
        while True:
            count = await worker.run_once()
            if count:
                print(f"Processed {count} escalation step(s)", flush=True)
            if args.command == "once":
                return
            await asyncio.sleep(1)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_run())
