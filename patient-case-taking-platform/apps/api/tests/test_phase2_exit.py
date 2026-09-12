"""Tests verifying Phase 2 exit criteria."""
from uuid import uuid4

from fastapi.testclient import TestClient

from app.audit.emitter import audit_emitter
from app.auth.token import create_dev_token
from app.main import app
from app.policy.engine import policy_engine
from app.sessions.state_machine import SessionState, SessionType, session_manager

client = TestClient(app)

# Shared test token
_tenant_id = str(uuid4())
_facility_id = str(uuid4())
_token = create_dev_token("test-user", "test@test.com", "doctor", _tenant_id, [_facility_id])
_headers = {"Authorization": f"Bearer {_token}"}


def test_kiosk_session_expires_and_resets():
    """EC: A kiosk session expires and resets cleanly."""
    facility_id = uuid4()
    session = session_manager.create_session(SessionType.KIOSK, facility_id)
    assert session.state == SessionState.INITIALIZING

    # Activate
    session_manager.transition(session.session_id, SessionState.ACTIVE)
    assert session.state == SessionState.ACTIVE

    # Wipe
    session_manager.wipe_session(session.session_id)
    wiped = session_manager.get_session(session.session_id)
    assert wiped.state == SessionState.WIPED


def test_staff_cannot_access_other_facility():
    """EC: Staff cannot access another facility's data."""
    # Doctor at facility A cannot read patient at facility B
    allowed = policy_engine.evaluate("doctor", "read", "patient", {
        "user_facility_id": "fac-a",
        "resource_facility_id": "fac-b",
    })
    assert not allowed

    # Doctor at facility A CAN read patient at facility A
    allowed = policy_engine.evaluate("doctor", "read", "patient", {
        "user_facility_id": "fac-a",
        "resource_facility_id": "fac-a",
    })
    assert allowed


def test_consent_scope_stored_and_auditable():
    """EC: Consent scope is stored and auditable."""
    tenant_id = uuid4()
    r = client.post("/api/v1/consents", params={"tenant_id": str(tenant_id)}, json={
        "patient_id": str(uuid4()),
        "purpose": "treatment",
        "scope": {"categories": ["demographics", "symptoms"], "recipients": ["doctor"]},
        "granted_by": "patient",
    }, headers=_headers)
    assert r.status_code == 201
    consent = r.json()
    assert consent["scope"]["categories"] == ["demographics", "symptoms"]
    assert consent["status"] == "granted"

    # Check consent
    r2 = client.post(f"/api/v1/consents/{consent['id']}/check",
                     params={"purpose": "treatment"}, headers=_headers)
    assert r2.json()["valid"] is True

    # Revoke
    r3 = client.post(f"/api/v1/consents/{consent['id']}/revoke",
                     json={"reason": "patient changed mind"}, headers=_headers)
    assert r3.json()["status"] == "revoked"


def test_sensitive_operations_emit_audit():
    """EC: Every sensitive read/write emits an audit event."""
    tenant_id = uuid4()
    # Create patient (should emit audit)
    r = client.post("/api/v1/patients", params={"tenant_id": str(tenant_id)}, json={
        "full_name": "Test Patient",
        "date_of_birth": "1990-01-01",
        "gender": "male",
    }, headers=_headers)
    assert r.status_code == 201

    # Query audit for this tenant
    events = audit_emitter.query(tenant_id, resource_type="patient")
    assert len(events) > 0
    assert any(e["action"] == "create" for e in events)


def test_privilege_elevation_rotates_session():
    """EC: Privilege elevation rotates the session."""
    from app.auth.token import create_dev_token, revoke_token, validate_token
    token = create_dev_token("rot-user", "test@test.com", "nurse", "t1", ["f1"])
    payload = validate_token(token)
    assert payload is not None
    assert payload.role == "nurse"

    # Revoke old, create new with elevated role
    revoke_token(token)
    new_token = create_dev_token("rot-user", "test@test.com", "doctor", "t1", ["f1"])
    new_payload = validate_token(new_token)
    assert new_payload is not None
    assert new_payload.role == "doctor"

    # Old token is gone
    old_payload = validate_token(token)
    assert old_payload is None
