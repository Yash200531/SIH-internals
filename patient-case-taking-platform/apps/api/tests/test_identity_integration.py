"""Real signature verification plus PostgreSQL grants and session revocation."""

import json
import os
import time
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI

from app.auth import service
from app.auth.dependencies import require_clinician
from app.auth.identity_repository import IdentityBinding, IdentityGrantConflict, IdentityRepository
from app.auth.jwt_verifier import ClerkSessionVerifier
from app.routers import identity_session

pytestmark = pytest.mark.skipif(os.getenv("IDENTITY_INTEGRATION") != "1", reason="Set IDENTITY_INTEGRATION=1 with local PostgreSQL")


async def test_signed_session_maps_internal_grants_and_revokes_durably(repositories, monkeypatch):
    pool, _ = repositories
    repository = IdentityRepository(pool)
    binding = IdentityBinding(
        issuer="https://identity.example.test", audience="patient-app", subject="user_test",
        internal_id=uuid4(), tenant_id=uuid4(), role="patient", facility_ids=(uuid4(),),
    )
    operator = uuid4()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())), "kid": "test"}
    boundary = service.ApplicationBoundary(
        issuer=binding.issuer, audience=binding.audience,
        authorized_parties=frozenset({"https://patient.example.test"}),
        allowed_roles=frozenset({"patient"}),
    )
    verifier = ClerkSessionVerifier(
        issuer=binding.issuer, audience=binding.audience, authorized_parties=boundary.authorized_parties,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"keys": [jwk]})),
    )
    monkeypatch.setattr(service.settings, "AUTH_PROVIDER", "clerk")
    monkeypatch.setattr(service, "configured_boundaries", lambda _: {(binding.issuer, binding.audience): (boundary, verifier)})
    monkeypatch.setattr(service, "get_identity_repository", AsyncMock(return_value=repository))
    monkeypatch.setattr(identity_session, "get_identity_repository", AsyncMock(return_value=repository))

    def credential(**changes):
        now = int(time.time())
        return jwt.encode({"iss": binding.issuer, "aud": binding.audience, "sub": binding.subject,
                           "sid": "sess_test", "azp": "https://patient.example.test", "iat": now,
                           "nbf": now-1, "exp": now+60, "role": "admin", "tenant_id": str(uuid4()),
                           "facility_ids": [str(uuid4())], **changes}, key, algorithm="RS256", headers={"kid": "test"})

    app = FastAPI()
    app.include_router(identity_session.router)

    @app.get("/staff")
    async def staff(user=Depends(require_clinician)):
        return {"role": user.role}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        client.headers["Authorization"] = f"Bearer {credential()}"
        assert (await client.get("/api/v1/auth/me")).status_code == 403
        assert await repository.grant(binding, operator_id=operator, reason_code="provision", expected_version=0) == 1
        result = await client.get("/api/v1/auth/me")
        assert result.status_code == 200, result.text
        assert result.headers["Cache-Control"] == "private, no-store"
        assert result.json()["user_id"] == str(binding.internal_id)
        assert result.json()["tenant_id"] == str(binding.tenant_id)
        assert result.json()["facility_ids"] == [str(binding.facility_ids[0])]
        assert result.json()["role"] == "patient"
        assert (await client.get("/staff")).status_code == 403
        await repository.grant(binding.model_copy(update={"role": "doctor"}), operator_id=operator, reason_code="scope_test", expected_version=1)
        assert (await client.get("/api/v1/auth/me")).status_code == 403
        await repository.grant(binding, operator_id=operator, reason_code="restore_patient", expected_version=2)
        assert (await client.post("/api/v1/auth/session/revoke")).status_code == 200
        client.headers["Authorization"] = f"Bearer {credential()}"
        assert (await client.get("/api/v1/auth/me")).status_code == 403
        client.headers["Authorization"] = f"Bearer {credential(sid='sess_new')}"
        assert (await client.get("/api/v1/auth/me")).status_code == 200
        await repository.grant(binding.model_copy(update={"active": False}), operator_id=operator, reason_code="deactivate", expected_version=3)
        assert (await client.get("/api/v1/auth/me")).status_code == 403
        client.headers["Authorization"] = f"Bearer {credential(aud='staff-app')}"
        assert (await client.get("/api/v1/auth/me")).status_code == 401
    with pytest.raises(IdentityGrantConflict):
        await repository.grant(binding, operator_id=operator, reason_code="stale", expected_version=1)
    with pytest.raises(IdentityGrantConflict, match="relinking"):
        await repository.grant(binding.model_copy(update={"internal_id": uuid4()}), operator_id=operator, reason_code="relink", expected_version=4)
    async with pool.acquire() as connection:
        async with connection.transaction():
            await repository.scope(connection, binding.issuer, binding.audience, binding.subject)
            assert await connection.fetchval("SELECT count(*) FROM auth_identity_history") == 4
            assert await connection.fetchval("SELECT count(*) FROM auth_revoked_session") == 1
        async with connection.transaction():
            await repository.scope(connection, binding.issuer, "different-app", binding.subject)
            assert await connection.fetchval("SELECT count(*) FROM auth_identity_binding") == 0
        with pytest.raises(asyncpg.RaiseError, match="append-only"):
            async with connection.transaction():
                await repository.scope(connection, binding.issuer, binding.audience, binding.subject)
                await connection.execute("UPDATE auth_identity_history SET reason_code='tamper'")
