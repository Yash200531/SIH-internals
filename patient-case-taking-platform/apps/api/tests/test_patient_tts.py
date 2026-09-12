import io
import wave

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.routers import tts

app = FastAPI()
app.include_router(tts.router)
client = TestClient(app)


def test_mock_tts_returns_deterministic_valid_wav() -> None:
    payload = {"text": "आपको दर्द कहाँ हो रहा है?", "language": "hi", "voice": "calm"}

    first = client.post("/api/v1/tts/synthesize", json=payload)
    second = client.post("/api/v1/tts/synthesize", json=payload)

    assert first.status_code == 200
    assert first.content == second.content
    assert first.headers["content-type"] == "audio/wav"
    assert first.headers["x-medikiosk-tts-provider"] == "mock"
    assert first.headers["x-medikiosk-tts-version"] == "mock-tone-v1"
    assert first.headers["cache-control"] == "no-store"
    with wave.open(io.BytesIO(first.content), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 16_000
        assert audio.getnframes() > 0


def test_mock_tts_changes_with_text_and_language() -> None:
    hindi = client.post(
        "/api/v1/tts/synthesize", json={"text": "दर्द", "language": "hi"}
    )
    english = client.post(
        "/api/v1/tts/synthesize", json={"text": "Pain", "language": "en"}
    )
    assert hindi.status_code == english.status_code == 200
    assert hindi.content != english.content


def test_tts_rejects_empty_or_oversized_text() -> None:
    assert client.post(
        "/api/v1/tts/synthesize", json={"text": "", "language": "hi"}
    ).status_code == 422
    assert client.post(
        "/api/v1/tts/synthesize", json={"text": "x" * 501, "language": "en"}
    ).status_code == 422


def test_tts_fails_closed_for_non_mock_provider(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TTS_PROVIDER", "remote")
    response = client.post(
        "/api/v1/tts/synthesize", json={"text": "hello", "language": "en"}
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "TTS provider unavailable"}
