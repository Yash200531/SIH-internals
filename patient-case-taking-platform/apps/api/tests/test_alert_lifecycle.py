"""Safety invariants for alert ownership and disposition."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.rules.alert_lifecycle import (
    AlertAction,
    AlertActor,
    AlertCommand,
    AlertConflict,
    AlertLifecycle,
    AlertState,
    transition_alert,
)


@pytest.fixture
def setup():
    now = datetime.now(UTC)
    tenant, facility = uuid4(), uuid4()
    alert = AlertLifecycle(
        id=uuid4(), tenant_id=tenant, facility_id=facility, encounter_id=uuid4(), updated_at=now
    )
    doctor = AlertActor(actor_id=uuid4(), tenant_id=tenant, facility_ids={facility}, role="doctor")
    return alert, doctor, now + timedelta(seconds=1)


def apply(alert, actor, now, action="acknowledge", **kwargs):
    return transition_alert(
        alert, AlertCommand(action=action, expected_version=alert.version, **kwargs), actor, now=now
    )


def test_acknowledgement_preserves_concern_and_disposition_is_separate(setup):
    alert, doctor, now = setup
    received = apply(alert, doctor, now).resulting
    assert received.state == AlertState.ACKNOWLEDGED
    assert received.resolved_at is None
    assert received.owner_actor_id == doctor.actor_id
    assert alert.state == AlertState.OPEN
    resolved = apply(
        received,
        doctor,
        now,
        "resolve",
        reason_code="assessed",
        rationale="Synthetic clinician assessment",
    ).resulting
    assert resolved.state == AlertState.RESOLVED
    assert resolved.version == 3
    with pytest.raises(AlertConflict):
        apply(resolved, doctor, now)


@pytest.mark.parametrize("change", ["tenant", "facility", "patient", "admin"])
def test_scope_and_role_denials(setup, change):
    alert, doctor, now = setup
    changes = {
        "tenant": {"tenant_id": uuid4()},
        "facility": {"facility_ids": frozenset({uuid4()})},
        "patient": {"role": "patient"},
        "admin": {"role": "admin"},
    }
    with pytest.raises(PermissionError):
        apply(alert, doctor.model_copy(update=changes[change]), now)


def test_stale_concurrent_acknowledgement_cannot_replace_owner(setup):
    alert, doctor, now = setup
    received = apply(alert, doctor, now).resulting
    other = doctor.model_copy(update={"actor_id": uuid4()})
    with pytest.raises(AlertConflict):
        transition_alert(
            received, AlertCommand(action="acknowledge", expected_version=1), other, now=now
        )


def test_handoff_needs_verified_target_and_recipient_acknowledgement(setup):
    alert, doctor, now = setup
    received = apply(alert, doctor, now).resulting
    target = doctor.model_copy(update={"actor_id": uuid4()})
    command = AlertCommand(
        action="handoff",
        expected_version=2,
        target_actor_id=target.actor_id,
        target_role="doctor",
        reason_code="shift_change",
    )
    with pytest.raises(PermissionError):
        transition_alert(received, command, doctor, now=now)
    handed = transition_alert(received, command, doctor, now=now, target=target).resulting
    assert handed.state == AlertState.OPEN
    assert handed.acknowledged_at is None
    assert handed.owner_actor_id == target.actor_id
    with pytest.raises(PermissionError, match="handoff recipient"):
        apply(handed, doctor, now)
    accepted = apply(handed, target, now).resulting
    assert accepted.owner_actor_id == target.actor_id
    assert accepted.state == AlertState.ACKNOWLEDGED


def test_timer_does_not_escalate_acknowledged_alert(setup):
    alert, doctor, now = setup
    worker = doctor.model_copy(update={"role": "alert_worker"})
    command = AlertCommand(action="escalate", expected_version=1)
    escalated = transition_alert(
        alert, command, worker, now=now, escalation_role="doctor"
    ).resulting
    assert escalated.state == AlertState.ESCALATED
    with pytest.raises(PermissionError):
        transition_alert(alert, command, doctor, now=now, escalation_role="doctor")
    received = apply(alert, doctor, now).resulting
    with pytest.raises(AlertConflict):
        transition_alert(
            received,
            command.model_copy(update={"expected_version": 2}),
            worker,
            now=now,
            escalation_role="doctor",
        )


def test_disposition_requires_owning_doctor_reason_and_override_approval(setup):
    alert, doctor, now = setup
    received = apply(alert, doctor, now).resulting
    for action in (AlertAction.RESOLVE, AlertAction.OVERRIDE):
        with pytest.raises(ValueError):
            apply(received, doctor, now, action)
        with pytest.raises(PermissionError):
            apply(
                received,
                doctor.model_copy(update={"actor_id": uuid4()}),
                now,
                action,
                reason_code="assessed",
                rationale="Synthetic rationale",
            )
    with pytest.raises(ValueError):
        apply(
            received,
            doctor,
            now,
            "override",
            reason_code="source_error",
            rationale="Synthetic rationale",
        )
    overridden = apply(
        received,
        doctor,
        now,
        "override",
        reason_code="source_error",
        rationale="Synthetic rationale",
        approval_reference="local-review-1",
    )
    assert overridden.resulting.state == AlertState.OVERRIDDEN
    assert overridden.previous_state == AlertState.ACKNOWLEDGED
    assert overridden.approval_reference == "local-review-1"


def test_transition_rejects_clock_regression(setup):
    alert, doctor, now = setup
    with pytest.raises(ValueError):
        apply(alert, doctor, now - timedelta(minutes=1))
