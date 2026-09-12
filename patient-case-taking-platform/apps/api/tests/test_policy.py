"""Tests for RBAC + ABAC policy engine."""
from app.policy.engine import policy_engine


def test_admin_full_access():
    assert policy_engine.evaluate("admin", "read", "patient", {"user_tenant_id": "t1", "resource_tenant_id": "t1"})


def test_doctor_can_read_patient():
    assert policy_engine.evaluate("doctor", "read", "patient", {"user_facility_id": "f1", "resource_facility_id": "f1"})


def test_doctor_cannot_read_different_facility():
    assert not policy_engine.evaluate("doctor", "read", "patient", {"user_facility_id": "f1", "resource_facility_id": "f2"})


def test_receptionist_can_write_patient():
    assert policy_engine.evaluate("receptionist", "write", "patient", {"user_facility_id": "f1", "resource_facility_id": "f1"})


def test_unknown_role_denied():
    assert not policy_engine.evaluate("hacker", "read", "patient")


def test_default_deny():
    assert not policy_engine.evaluate("doctor", "delete", "patient")
