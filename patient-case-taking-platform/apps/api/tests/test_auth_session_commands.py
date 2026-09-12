"""HTTP session commands must invalidate credentials, not just emit an audit."""

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.token import create_dev_token, validate_token
from app.routers.auth import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def token():
    return create_dev_token(
        str(uuid4()), "synthetic@example.test", "nurse", str(uuid4()), [str(uuid4())],
        mfa_verified=True, session_id="synthetic-session",
    )


def test_revoke_invalidates_token_immediately():
    original = token()
    auth = {"Authorization": f"Bearer {original}"}
    assert client.post("/api/v1/auth/revoke", headers=auth).status_code == 200
    assert validate_token(original) is None
    assert client.post("/api/v1/auth/revoke", headers=auth).status_code == 401


def test_rotation_invalidates_old_token_and_preserves_scope():
    original = token()
    before = validate_token(original)
    response = client.post("/api/v1/auth/token/rotate", headers={"Authorization": f"bearer {original}"})
    assert response.status_code == 200
    assert validate_token(original) is None
    after = validate_token(response.json()["token"])
    assert before is not None and after is not None
    assert (after.role, after.tenant_id, after.facility_ids, after.session_id, after.mfa_verified) == (
        before.role, before.tenant_id, before.facility_ids, before.session_id, before.mfa_verified,
    )


def test_rotation_cannot_elevate_role():
    original = token()
    response = client.post("/api/v1/auth/token/rotate?new_role=admin", headers={"Authorization": f"Bearer {original}"})
    assert response.status_code == 403
    assert validate_token(original).role == "nurse"


def test_non_bearer_credentials_are_rejected():
    original = token()
    for value in (original, f"Basic {original}", "Bearer "):
        assert client.post("/api/v1/auth/revoke", headers={"Authorization": value}).status_code == 401
