"""Voice access must fail before inference, and again on consent revocation."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.asr.authorization import authorize_voice
from app.auth.token import create_dev_token
from app.routers import asr


@pytest.fixture
def grant(monkeypatch):
    tenant, patient, encounter, consent = (uuid4() for _ in range(4))
    token = create_dev_token(str(patient), None, "patient", str(tenant), [str(uuid4())])
    row = dict(
        patient_id=patient,
        encounter_id=encounter,
        purpose="treatment",
        status="granted",
        scope={"audio_retention": False},
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    connection = MagicMock()
    connection.transaction.return_value.__aenter__ = AsyncMock()
    connection.transaction.return_value.__aexit__ = AsyncMock()
    connection.execute = AsyncMock()
    connection.fetchrow = AsyncMock(return_value=row)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=connection)
    pool.acquire.return_value.__aexit__ = AsyncMock()
    monkeypatch.setattr("app.asr.authorization.get_postgres_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr("app.asr.authorization.IntakeSessionRepository.access", AsyncMock(return_value={"encounter_id": encounter}))
    return token, tenant, patient, encounter, consent, row, connection


async def test_active_patient_consent_authorizes_and_scopes_query(grant):
    token, tenant, patient, encounter, consent, _, connection = grant
    assert await authorize_voice(token, tenant, encounter, consent, session_id=uuid4()) == patient
    connection.execute.assert_awaited_once_with(
        "SELECT set_config('app.tenant_id', $1, true)", str(tenant)
    )
    assert connection.fetchrow.call_args.args[1:] == (tenant, consent)


@pytest.mark.parametrize(
    "change",
    [
        "patient",
        "encounter",
        "purpose",
        "revoked",
        "expired",
        "retention",
        "missing",
        "token",
        "tenant",
        "role",
    ],
)
async def test_voice_authorization_denies_invalid_scope(grant, change):
    token, tenant, patient, encounter, consent, row, connection = grant
    if change == "patient":
        row["patient_id"] = uuid4()
    if change == "encounter":
        row["encounter_id"] = uuid4()
    if change == "purpose":
        row["purpose"] = "research"
    if change == "revoked":
        row["status"] = "revoked"
    if change == "expired":
        row["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    if change == "missing":
        connection.fetchrow.return_value = None
    if change == "token":
        token = "invalid"
    if change == "tenant":
        tenant = uuid4()
    if change == "role":
        token = create_dev_token(str(patient), None, "doctor", str(tenant), [str(uuid4())])
    with pytest.raises(HTTPException) as denied:
        await authorize_voice(token, tenant, encounter, consent, change == "retention", session_id=uuid4())
    assert denied.value.status_code in (401, 403)


async def test_stored_retention_grant_authorizes_retention(grant):
    token, tenant, patient, encounter, consent, row, _ = grant
    row["scope"] = '{"audio_retention":true}'
    assert await authorize_voice(token, tenant, encounter, consent, True, session_id=uuid4()) == patient


def test_socket_denies_audio_before_authentication(monkeypatch):
    provider = MagicMock()
    monkeypatch.setattr(asr, "get_provider_for_language", provider)
    app = FastAPI()
    app.include_router(asr.router)
    query = "&".join(
        f"{key}={uuid4()}" for key in ("tenant_id", "session_id", "encounter_id", "consent_id")
    )
    with TestClient(app).websocket_connect(f"/ws/asr?{query}") as socket:
        socket.send_bytes(b"unauthenticated audio")
        assert socket.receive_json()["code"] == "voice_access_denied"
    provider.assert_not_called()


def test_socket_rechecks_consent_after_inference(monkeypatch):
    authorize = AsyncMock(
        side_effect=[uuid4(), uuid4(), HTTPException(403, "Active treatment consent required")]
    )
    monkeypatch.setattr(asr, "authorize_voice", authorize)
    retain = AsyncMock()
    monkeypatch.setattr(asr.voice_runtime, "retain", retain)
    app = FastAPI()
    app.include_router(asr.router)
    query = "&".join(
        f"{key}={uuid4()}" for key in ("tenant_id", "session_id", "encounter_id", "consent_id")
    )
    with TestClient(app).websocket_connect(f"/ws/asr?{query}") as socket:
        socket.send_json({"type": "authenticate", "access_token": "test"})
        assert socket.receive_json()["type"] == "ready"
        socket.send_bytes(b"\x00\x00" * 100)
        socket.send_json({"type": "end"})
        assert socket.receive_json()["code"] == "voice_access_denied"
    retain.assert_not_awaited()


def test_rest_requires_bearer_before_processing():
    app = FastAPI()
    app.include_router(asr.router)
    response = TestClient(app).post(
        "/api/v1/asr/transcribe",
        files={"file": ("a.wav", b"audio", "audio/wav")},
        data={key: str(uuid4()) for key in ("tenant_id", "session_id", "encounter_id", "consent_id")},
    )
    assert response.status_code == 401


@pytest.mark.parametrize("mismatch", [False, True])
async def test_voice_requires_active_matching_session(grant, monkeypatch, mismatch):
    from app.patient_portal.sessions import IntakeSessionUnavailable

    token, tenant, _, encounter, consent, _, connection = grant
    access = AsyncMock(return_value={"encounter_id": uuid4()}) if mismatch else AsyncMock(side_effect=IntakeSessionUnavailable())
    monkeypatch.setattr("app.asr.authorization.IntakeSessionRepository.access", access)
    with pytest.raises(HTTPException, match="Active patient intake session required"):
        await authorize_voice(token, tenant, encounter, consent, session_id=uuid4())
    connection.fetchrow.assert_not_awaited()


def test_socket_does_not_release_partial_after_session_ends(monkeypatch):
    from types import SimpleNamespace

    authorize = AsyncMock(side_effect=[uuid4(), uuid4(), HTTPException(403, "Active patient intake session required")])
    monkeypatch.setattr(asr, "authorize_voice", authorize)
    quality = SimpleNamespace(has_speech=True, as_dict=lambda: {})
    monkeypatch.setattr(asr, "analyze_pcm16", lambda _: quality)
    monkeypatch.setattr(asr.settings, "ASR_PARTIAL_INTERVAL_BYTES", 2)
    provider = SimpleNamespace(transcribe_file=AsyncMock(return_value=SimpleNamespace(text="private transcript", confidence=1, language="en")))
    monkeypatch.setattr(asr, "get_provider_for_language", lambda _: provider)
    app = FastAPI()
    app.include_router(asr.router)
    query = "&".join(f"{key}={uuid4()}" for key in ("tenant_id", "session_id", "encounter_id", "consent_id"))
    with TestClient(app).websocket_connect(f"/ws/asr?{query}") as socket:
        socket.send_json({"type": "authenticate", "access_token": "test"})
        assert socket.receive_json()["type"] == "ready"
        socket.send_bytes(b"\x00\x00")
        message = socket.receive_json()
        assert message["code"] == "voice_access_denied"
        assert "text" not in message
    provider.transcribe_file.assert_awaited_once()
