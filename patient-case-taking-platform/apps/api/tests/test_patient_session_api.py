from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.auth.dependencies import get_current_user
from app.auth.token import create_dev_token, validate_token
from app.patient_portal.sessions import IntakeSessionUnavailable, session_owner
from app.routers import patient_sessions


def setup(role="patient"):
    facility = uuid4()
    token = create_dev_token(str(uuid4()), None, role, str(uuid4()), [str(facility)])
    user = validate_token(token)
    app = FastAPI()
    app.include_router(patient_sessions.router)
    repo = AsyncMock()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[patient_sessions.repository] = lambda: repo
    return app, repo, facility


@pytest.mark.parametrize("role,wrong_facility", [("doctor", False), ("patient", True)])
async def test_session_creation_rejects_wrong_role_or_facility(role, wrong_facility):
    app, repo, facility = setup(role)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/patient-portal/me/sessions", headers={"Idempotency-Key": str(uuid4())},
                                     json={"facility_id": str(uuid4() if wrong_facility else facility), "language": "hi"})
    assert response.status_code == 403
    repo.create.assert_not_awaited()


async def test_session_lifecycle_responses_are_private_and_scope_denial_is_opaque():
    app, repo, facility = setup()
    repo.create.return_value = {"id": str(uuid4()), "encounter_id": str(uuid4())}
    repo.access.side_effect = IntakeSessionUnavailable("private ownership detail")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/patient-portal/me/sessions", headers={"Idempotency-Key": str(uuid4())},
                                     json={"facility_id": str(facility), "language": "hi"})
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "private, no-store"
        denied = await client.post(f"/api/v1/patient-portal/me/sessions/{uuid4()}/touch")
        assert denied.status_code == 404
        assert "private ownership detail" not in denied.text


def test_owner_key_is_stable_over_provider_refresh_but_separate_by_login_and_application():
    user = validate_token(create_dev_token(str(uuid4()), None, "patient", str(uuid4()), [str(uuid4())]))
    user.external_issuer = "https://identity.example.test"
    user.external_audience = "patient-app"
    user.external_subject = "user_test"
    user.session_id = "session_test"
    owner = session_owner(user)
    user.token_hash = "refreshed-token-hash"
    assert session_owner(user) == owner
    user.external_audience = "other-app"
    assert session_owner(user) != owner
    user.external_audience = "patient-app"
    user.session_id = "other-login"
    assert session_owner(user) != owner
