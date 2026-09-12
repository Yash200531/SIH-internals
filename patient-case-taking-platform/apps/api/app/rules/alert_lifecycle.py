"""Pure alert lifecycle: receipt, ownership and clinical disposition are distinct."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AlertState(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    OVERRIDDEN = "overridden"


class AlertAction(StrEnum):
    ACKNOWLEDGE = "acknowledge"
    HANDOFF = "handoff"
    ESCALATE = "escalate"
    RESOLVE = "resolve"
    OVERRIDE = "override"


class AlertConflict(ValueError):
    """Stale version or illegal lifecycle transition."""


class AlertActor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    actor_id: UUID
    tenant_id: UUID
    facility_ids: frozenset[UUID]
    role: str


class AlertLifecycle(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: UUID
    tenant_id: UUID
    facility_id: UUID
    encounter_id: UUID
    version: int = Field(default=1, ge=1)
    state: AlertState = AlertState.OPEN
    owner_role: str = "nurse"
    owner_actor_id: UUID | None = None
    acknowledged_at: datetime | None = None
    escalated_at: datetime | None = None
    resolved_at: datetime | None = None
    updated_at: datetime


class AlertCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    action: AlertAction
    expected_version: int = Field(ge=1)
    reason_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    rationale: str | None = Field(default=None, min_length=1, max_length=2000)
    target_actor_id: UUID | None = None
    target_role: str | None = None
    approval_reference: str | None = Field(default=None, min_length=1, max_length=128)


class AlertTransition(BaseModel):
    model_config = ConfigDict(frozen=True)
    previous_state: AlertState
    resulting: AlertLifecycle
    action: AlertAction
    actor_id: UUID
    reason_code: str | None
    # Protected history only: these fields must never be copied into events/logs.
    rationale: str | None
    approval_reference: str | None


def transition_alert(
    alert: AlertLifecycle,
    command: AlertCommand,
    actor: AlertActor,
    *,
    now: datetime,
    target: AlertActor | None = None,
    escalation_role: str | None = None,
) -> AlertTransition:
    """Validate one transition; caller atomically stores projection/history/outbox.

    Actor and handoff target must come from verified workforce identities.
    Escalation role is supplied by the facility policy adapter, never client input.
    This function does not equate an acknowledgement with clinical resolution.
    """
    if now.tzinfo is None or alert.updated_at.tzinfo is None or now < alert.updated_at:
        raise ValueError("A monotonic timezone-aware transition time is required")
    if actor.tenant_id != alert.tenant_id or alert.facility_id not in actor.facility_ids:
        raise PermissionError("Alert scope denied")
    is_worker = actor.role == "alert_worker"
    if actor.role not in {"doctor", "nurse", "alert_worker"}:
        raise PermissionError("Clinical alert role required")
    if command.expected_version != alert.version:
        raise AlertConflict("Alert version is stale")
    if alert.state in {AlertState.RESOLVED, AlertState.OVERRIDDEN}:
        raise AlertConflict("Terminal alerts cannot be changed")
    action = command.action
    if is_worker != (action == AlertAction.ESCALATE):
        raise PermissionError(
            "Escalation requires the policy worker; clinical commands require staff"
        )
    if action != AlertAction.HANDOFF and (command.target_actor_id or command.target_role):
        raise ValueError("Handoff target is only valid for handoff")
    if action != AlertAction.OVERRIDE and command.approval_reference:
        raise ValueError("Approval reference is only valid for override")
    updates: dict = {"version": alert.version + 1, "updated_at": now}
    if action == AlertAction.ACKNOWLEDGE:
        if alert.state not in {AlertState.OPEN, AlertState.ESCALATED}:
            raise AlertConflict("Alert is already acknowledged; use handoff")
        if alert.owner_actor_id is not None and alert.owner_actor_id != actor.actor_id:
            raise PermissionError("Only the assigned handoff recipient may acknowledge")
        if actor.role != alert.owner_role and actor.role != "doctor":
            raise PermissionError("Required owner role does not match")
        updates.update(
            state=AlertState.ACKNOWLEDGED,
            owner_actor_id=actor.actor_id,
            owner_role=actor.role,
            acknowledged_at=now,
        )
    elif action == AlertAction.HANDOFF:
        if alert.state != AlertState.ACKNOWLEDGED or actor.actor_id != alert.owner_actor_id:
            raise PermissionError("Only the acknowledged owner may hand off")
        if (
            target is None
            or target.actor_id != command.target_actor_id
            or target.role != command.target_role
            or target.role not in {"doctor", "nurse"}
            or target.tenant_id != alert.tenant_id
            or alert.facility_id not in target.facility_ids
            or target.actor_id == actor.actor_id
        ):
            raise PermissionError("Verified clinical handoff target required")
        if not command.reason_code:
            raise ValueError("Handoff reason required")
        # A handoff request does not fabricate the recipient's acknowledgement.
        updates.update(
            state=AlertState.OPEN,
            owner_actor_id=target.actor_id,
            owner_role=target.role,
            acknowledged_at=None,
        )
    elif action == AlertAction.ESCALATE:
        if alert.state not in {AlertState.OPEN, AlertState.ESCALATED}:
            raise AlertConflict("Acknowledged alerts cannot expire on an acknowledgement timer")
        if escalation_role not in {"nurse", "doctor"}:
            raise ValueError("Facility escalation owner role required")
        if alert.owner_role == "doctor" and escalation_role == "nurse":
            raise ValueError("Escalation cannot lower the required owner role")
        updates.update(
            state=AlertState.ESCALATED,
            owner_actor_id=None,
            owner_role=escalation_role,
            escalated_at=now,
        )
    else:
        if actor.role != "doctor" or actor.actor_id != alert.owner_actor_id:
            raise PermissionError("Disposition requires the owning doctor")
        if alert.state != AlertState.ACKNOWLEDGED:
            raise AlertConflict("Acknowledge before clinical disposition")
        if not command.reason_code or not command.rationale or not command.rationale.strip():
            raise ValueError("Disposition reason and protected rationale required")
        if action == AlertAction.OVERRIDE and not command.approval_reference:
            raise ValueError("Governed override approval reference required")
        updates.update(
            state=AlertState.RESOLVED if action == AlertAction.RESOLVE else AlertState.OVERRIDDEN,
            resolved_at=now,
        )
    return AlertTransition(
        previous_state=alert.state,
        resulting=alert.model_copy(update=updates),
        action=action,
        actor_id=actor.actor_id,
        reason_code=command.reason_code,
        rationale=command.rationale,
        approval_reference=command.approval_reference,
    )
