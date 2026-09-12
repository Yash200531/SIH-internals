"""Alert API must use staff identity and persisted confirmed evidence."""
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.token import create_dev_token
from app.patient_portal.worklist import IntakeHandoff
from app.routers import alerts
from app.rules.alert_lifecycle import AlertConflict
from app.rules.alert_repository import AlertNotFound


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(alerts.router)
    worklist = AsyncMock()
    repository = AsyncMock()
    repository.list_flags.return_value = []
    repository.raise_flag.return_value = {"id": str(uuid4())}
    app.dependency_overrides[alerts.get_worklist] = lambda: worklist
    app.dependency_overrides[alerts.get_alert_repository] = lambda: repository
    tenant, facility, actor = uuid4(), uuid4(), uuid4()
    def headers(role="doctor", tenant_id=tenant):
        token = create_dev_token(str(actor), None, role, str(tenant_id), [str(facility)])
        return {"Authorization": f"Bearer {token}", "Idempotency-Key": "test-command"}
    return TestClient(app), worklist, repository, tenant, facility, actor, headers


def test_alert_list_requires_clinician_and_purpose(api):
    client, _, repository, tenant, _, actor, headers = api
    path = "/api/v1/alerts?purpose=treatment"
    assert client.get(path).status_code == 401
    for role in ("patient", "admin"):
        assert client.get(path, headers=headers(role)).status_code == 403
    assert client.get("/api/v1/alerts", headers=headers()).status_code == 422
    response = client.get(path, headers=headers())
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    scope = repository.list_flags.call_args.args[0]
    assert scope.actor_id == actor and scope.tenant_id == tenant


def test_evaluation_loads_consented_intake_and_rejects_supplied_sources(api):
    client, worklist, repository, tenant, facility, _, headers = api
    intake = IntakeHandoff(id=uuid4(), facility_id=facility, patient_id=uuid4(), encounter_id=uuid4(),
                           language="en", chief_complaint="cannot breathe", confirmed_answers={},
                           created_at=datetime.now(UTC), context_version=None)
    worklist.read.return_value = [intake]
    path = f"/api/v1/alerts/from-intake/{intake.id}?purpose=treatment"
    assert client.post(path, headers=headers(), json={"reviewed": False}).status_code == 422
    assert client.post(path, headers=headers(), json={"reviewed": True, "chief_complaint": "other"}).status_code == 422
    response = client.post(path, headers=headers(), json={"reviewed": True})
    assert response.status_code == 200
    assert response.json()["outcome"] == "flags_triggered"
    assert response.json()["staff_notification_sent"] is False
    assert worklist.read.call_args.args == (tenant, {facility})
    assert repository.raise_flag.call_args.kwargs["encounter_id"] == intake.encounter_id
    assert repository.raise_flag.call_args.kwargs["rule"].evidence_paths == ("chief_complaint",)
    worklist.read.return_value = []
    assert client.post(path, headers=headers(), json={"reviewed": True}).status_code == 404


@pytest.mark.parametrize("error,status", [(AlertNotFound(),404),(AlertConflict("stale"),409),(PermissionError("owner"),403),(ValueError("reason"),422)])
def test_command_failure_statuses(api, error, status):
    client, _, repository, _, _, _, headers = api
    repository.command.side_effect = error
    path = f"/api/v1/alerts/{uuid4()}/commands?purpose=treatment"
    assert client.post(path, headers=headers(), json={"action":"acknowledge","expected_version":1}).status_code == status


def test_unverified_handoff_override_and_timer_cannot_be_client_commands(api):
    client, _, repository, _, _, _, headers = api
    path = f"/api/v1/alerts/{uuid4()}/commands?purpose=treatment"
    for action in ("handoff", "override", "escalate"):
        assert client.post(path, headers=headers(), json={"action":action,"expected_version":1}).status_code == 422
    repository.command.assert_not_called()


def test_prototype_rule_gate_is_independent_of_history_access(api, monkeypatch):
    client, worklist, _, _, _, _, headers = api
    monkeypatch.setattr(alerts.settings, "ENABLE_DEMO_ROUTES", False)
    response = client.post(f"/api/v1/alerts/from-intake/{uuid4()}?purpose=treatment", headers=headers(), json={"reviewed":True})
    assert response.status_code == 503
    worklist.read.assert_not_called()
    assert client.get("/api/v1/alerts?purpose=treatment", headers=headers()).status_code == 200
