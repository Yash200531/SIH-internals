from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.rules.alert_timers import FacilityEscalationPolicy


def policy(**changes):
    return FacilityEscalationPolicy(
        **{
            "tenant_id": uuid4(), "facility_id": uuid4(), "worker_actor_id": uuid4(),
            "policy_id": "synthetic-test", "version": "v1", "owner_reference": "test-owner",
            "steps": [{"after_seconds": 30}, {"after_seconds": 120}], **changes,
        }
    )


@pytest.mark.parametrize("steps", [[], [{"after_seconds": 0}], [{"after_seconds": 2}, {"after_seconds": 1}], [{"after_seconds": 2}, {"after_seconds": 2}], [{"after_seconds": 1, "owner_role": "nurse"}]])
def test_policy_rejects_missing_unbounded_or_lowering_ladder(steps):
    with pytest.raises(ValidationError):
        policy(steps=steps)


def test_policy_fingerprint_covers_full_configuration_and_roundtrips():
    original = policy()
    assert FacilityEscalationPolicy.model_validate_json(original.model_dump_json()).fingerprint == original.fingerprint
    changed = original.model_copy(update={"version": "v2"})
    assert changed.fingerprint != original.fingerprint
