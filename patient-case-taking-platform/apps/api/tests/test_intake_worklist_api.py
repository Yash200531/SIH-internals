from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.token import create_dev_token
from app.main import app
from app.patient_portal.worklist import IntakeHandoff
from app.routers.intake_worklist import get_worklist
from app.summary_workflow.context import InMemorySummaryContextRepository
from app.summary_workflow.dependencies import get_summary_context_repository


@pytest.fixture
def handoff():
    tenant, facility = uuid4(), uuid4()
    item = IntakeHandoff(
        id=uuid4(), facility_id=facility, patient_id=uuid4(), encounter_id=uuid4(),
        language="en", chief_complaint="Synthetic headache", confirmed_answers={"site": "head"},
        created_at=datetime.now(UTC), context_version=None,
    )

    class Repository:
        async def read(self, requested_tenant, facilities, **kwargs):
            if requested_tenant != tenant or facility not in facilities:
                return []
            if kwargs.get("intake_id") not in (None, item.id):
                return []
            return [item]

    app.dependency_overrides[get_worklist] = Repository
    # Share one context repository across requests to test optimistic concurrency.
    contexts = InMemorySummaryContextRepository()
    app.dependency_overrides[get_summary_context_repository] = lambda: contexts
    yield tenant, facility, item
    app.dependency_overrides.pop(get_worklist)
    app.dependency_overrides.pop(get_summary_context_repository)


def headers(tenant, facility, role="nurse"):
    token = create_dev_token(str(uuid4()), None, role, str(tenant), [str(facility)])
    return {"Authorization": f"Bearer {token}"}


def test_worklist_role_scope_and_purpose(handoff):
    tenant, facility, item = handoff
    client = TestClient(app)
    path = "/api/v1/intake-worklist?purpose=treatment"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=headers(tenant, facility, "patient")).status_code == 403
    assert client.get("/api/v1/intake-worklist", headers=headers(tenant, facility)).status_code == 422
    assert client.get(path, headers=headers(uuid4(), facility)).json() == []
    assert client.get(path, headers=headers(tenant, uuid4())).json() == []
    response = client.get(path, headers=headers(tenant, facility))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()[0]["id"] == str(item.id)


def test_confirmation_uses_server_source_and_requires_review(handoff):
    tenant, facility, item = handoff
    client = TestClient(app)
    path = f"/api/v1/intake-worklist/{item.id}/confirm"
    auth = headers(tenant, facility)
    assert client.post(path, headers=auth, json={"reviewed": False}).status_code == 422
    assert client.post(path, headers=headers(tenant, uuid4()), json={"reviewed": True}).status_code == 404
    response = client.post(path, headers=auth, json={"reviewed": True})
    assert response.status_code == 200
    assert response.json()["chief_complaint"] == item.chief_complaint
    assert response.json()["patient_id"] == str(item.patient_id)
    assert client.post(path, headers=auth, json={"reviewed": True}).status_code == 409
