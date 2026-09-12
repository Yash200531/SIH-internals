"""Phase 4 voice contract and acoustic quality tests."""

from array import array
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.asr.quality import analyze_pcm16
from app.asr.runtime import RetentionUnavailable, VoiceTurnContext, voice_runtime
from app.routers import asr

app = FastAPI()
app.include_router(asr.router)
client = TestClient(app)


def setup_function() -> None:
    voice_runtime.contexts.clear()
    voice_runtime.events.clear()


def _speech_pcm(seconds: int = 3) -> bytes:
    samples = array("h")
    for index in range(16_000 * seconds):
        active = (index // 4_000) % 2 == 1
        samples.append(8_000 if active and index % 2 == 0 else -8_000 if active else 0)
    return samples.tobytes()


def _voice_url(**overrides) -> str:
    values = {
        "tenant_id": uuid4(),
        "session_id": uuid4(),
        "encounter_id": uuid4(),
        "consent_id": uuid4(),
    }
    values.update(overrides)
    query = "&".join(f"{key}={value}" for key, value in values.items())
    return f"/ws/asr?language=hi&{query}"


def test_signal_quality_rejects_silence() -> None:
    quality = analyze_pcm16(b"\x00\x00" * 16_000)
    assert quality.has_speech is False
    assert quality.score == 0.0


def test_signal_quality_accepts_speech_bursts() -> None:
    quality = analyze_pcm16(_speech_pcm())
    assert quality.has_speech is True
    assert quality.score >= 0.35


def test_websocket_requires_auditable_context() -> None:
    with client.websocket_connect("/ws/asr?language=hi") as websocket:
        message = websocket.receive_json()
        assert message["code"] == "voice_context_required"
        assert message["fallback"] == "touch"


def test_websocket_rejects_unsupported_language_with_touch_fallback() -> None:
    with client.websocket_connect(_voice_url().replace("language=hi", "language=fr")) as websocket:
        message = websocket.receive_json()
        assert message["code"] == "unsupported_language"
        assert message["fallback"] == "touch"


def test_websocket_emits_partial_and_final_transcripts(monkeypatch) -> None:
    monkeypatch.setattr(asr.settings, "ASR_PARTIAL_INTERVAL_BYTES", 16_000)
    with client.websocket_connect(_voice_url()) as websocket:
        assert websocket.receive_json()["type"] == "ready"
        websocket.send_bytes(_speech_pcm())
        partial = websocket.receive_json()
        assert partial["type"] == "transcript"
        assert partial["is_final"] is False
        websocket.send_json({"type": "end"})
        final = websocket.receive_json()
        done = websocket.receive_json()

    assert final["is_final"] is True
    assert final["signal_quality"]["has_speech"] is True
    assert done["type"] == "done"
    assert done["result"]["turn_id"]
    assert voice_runtime.events[-1][0] == "ai.asr.completed.v1"
    assert "transcript" not in voice_runtime.events[-1][1]
    assert voice_runtime.contexts[done["result"]["turn_id"]]["status"] == "complete"


def test_requested_retention_fails_closed_when_storage_is_disabled() -> None:
    url = _voice_url(retain_audio="true", audio_retention_consent="true")
    with client.websocket_connect(url) as websocket:
        assert websocket.receive_json()["type"] == "ready"
        websocket.send_bytes(_speech_pcm())
        websocket.send_json({"type": "end"})
        message = websocket.receive_json()
        while message["type"] == "transcript":
            message = websocket.receive_json()

    assert message["code"] == "audio_retention_unavailable"
    assert message["fallback"] == "touch"


async def test_retention_requires_explicit_consent(monkeypatch) -> None:
    monkeypatch.setattr(asr.settings, "AUDIO_RETENTION_ENABLED", True)
    context = VoiceTurnContext(
        tenant_id=uuid4(),
        session_id=uuid4(),
        encounter_id=uuid4(),
        consent_id=uuid4(),
        turn_id=uuid4(),
        language="hi",
        retain_audio=True,
        audio_retention_consent=False,
    )
    try:
        await voice_runtime.retain(context, b"audio")
    except RetentionUnavailable as exc:
        assert "consent" in str(exc).lower()
    else:
        raise AssertionError("Retention must fail without explicit consent")


# Speech mechanics are isolated from access control; real denial cases live in
# test_voice_authorization.py. No runtime bypass exists.
@pytest.fixture(autouse=True)
def authorized_speech_contract(monkeypatch):
    monkeypatch.setattr("app.routers.asr._authenticate_socket", AsyncMock(return_value="test"))
    monkeypatch.setattr("app.routers.asr.authorize_voice", AsyncMock(return_value=uuid4()))
