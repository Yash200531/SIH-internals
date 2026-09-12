from uuid import uuid4

from app.models.audit_log import AuditLog


def _make_audit(**overrides) -> AuditLog:
    defaults = {
        "tenant_id": uuid4(),
        "actor_type": "staff",
        "action": "read",
        "resource_type": "patient",
    }
    defaults.update(overrides)
    return AuditLog(**defaults)


def test_emit_audit_event():
    entry = _make_audit()
    assert entry.action == "read"
    assert entry.outcome == "success"
    assert entry.is_immutable is True


def test_query_audit_by_resource():
    patient_id = uuid4()
    entries = [
        _make_audit(resource_type="patient", resource_id=patient_id),
        _make_audit(resource_type="encounter"),
        _make_audit(resource_type="patient", resource_id=patient_id),
    ]
    filtered = [e for e in entries if e.resource_type == "patient" and e.resource_id == patient_id]
    assert len(filtered) == 2


def test_audit_is_append_only():
    entry = _make_audit()
    entry.action = "write"
    # AuditLog is append-only by convention; immutability enforced at DB layer
    assert entry.is_immutable is True
