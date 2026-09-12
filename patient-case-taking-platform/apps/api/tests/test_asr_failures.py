"""Failures before recording must preserve the manual-entry fallback."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _url():
    return "/ws/asr?language=hi&" + "&".join(
        f"{key}={uuid4()}"
        for key in ("tenant_id", "session_id", "encounter_id", "consent_id")
    )


def test_missing_provider_returns_safe_manual_fallback(monkeypatch):
    def unavailable(_language):
        raise RuntimeError("private provider configuration")

    monkeypatch.setattr("app.routers.asr.get_provider_for_language", unavailable)
    with TestClient(app).websocket_connect(_url()) as socket:
        result = socket.receive_json()
        assert result["code"] == "asr_unavailable"
        assert result["fallback"] == "touch"
        assert "private" not in str(result)


def test_context_store_failure_does_not_announce_ready(monkeypatch):
    monkeypatch.setattr(
        "app.routers.asr.voice_runtime.save_context",
        AsyncMock(side_effect=ConnectionError("Redis unavailable")),
    )
    with TestClient(app).websocket_connect(_url()) as socket:
        result = socket.receive_json()
        assert result["type"] == "error"
        assert result["fallback"] == "touch"


def test_non_object_control_message_can_be_corrected():
    with TestClient(app).websocket_connect(_url()) as socket:
        assert socket.receive_json()["type"] == "ready"
        socket.send_json([])
        assert socket.receive_json()["detail"] == "Invalid control message"
        socket.send_json({"type": "end"})
        assert socket.receive_json()["detail"] == "No audio received"


# Speech mechanics are isolated from access control; real denial cases live in
# test_voice_authorization.py. No runtime bypass exists.
@pytest.fixture(autouse=True)
def authorized_speech_contract(monkeypatch):
    monkeypatch.setattr("app.routers.asr._authenticate_socket", AsyncMock(return_value="test"))
    monkeypatch.setattr("app.routers.asr.authorize_voice", AsyncMock(return_value=uuid4()))
