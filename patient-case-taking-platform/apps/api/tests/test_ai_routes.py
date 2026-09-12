"""Contract tests for bounded ASR and OCR upload routes."""

import base64
import io
import wave
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ocr.mock_provider import MockOCRProvider
from app.ocr.registry import set_active_provider
from app.routers import asr, ocr

app = FastAPI()
app.include_router(asr.router)
app.include_router(ocr.router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def _use_mock_ocr_provider():
    """Keep route contract tests deterministic without weakening runtime defaults."""
    set_active_provider(MockOCRProvider())
    yield
    set_active_provider(None)


def _silent_wav() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\x00\x00" * 1_600)
    return output.getvalue()


def test_asr_transcribes_the_uploaded_file() -> None:
    response = client.post(
        "/api/v1/asr/transcribe",
        files={"file": ("sample.wav", _silent_wav(), "audio/wav")},
        data={"language": "hi", "session_id": str(uuid4()), "tenant_id": str(uuid4()), "encounter_id": str(uuid4()), "consent_id": str(uuid4())},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    assert response.json()["provider"] == "mock"
    assert "processing_ms" in response.json()


def test_asr_rejects_empty_upload() -> None:
    response = client.post(
        "/api/v1/asr/transcribe",
        files={"file": ("empty.wav", b"", "audio/wav")},
        data={"language": "hi", "session_id": str(uuid4()), "tenant_id": str(uuid4()), "encounter_id": str(uuid4()), "consent_id": str(uuid4())},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 400


def test_ocr_uses_configured_mock_provider() -> None:
    response = client.post(
        "/api/v1/ocr/recognize",
        files={"file": ("document.png", b"valid-test-payload", "image/png")},
    )
    assert response.status_code == 200
    assert response.json()["provider"] == "mock"


def test_ocr_base64_rejects_malformed_input() -> None:
    response = client.post(
        "/api/v1/ocr/recognize-base64",
        params={"image": "not*base64", "mime_type": "image/png"},
    )
    assert response.status_code == 400


def test_ocr_base64_accepts_bounded_input() -> None:
    encoded = base64.b64encode(b"valid-test-payload").decode()
    response = client.post(
        "/api/v1/ocr/recognize-base64",
        params={"image": encoded, "mime_type": "image/png"},
    )
    assert response.status_code == 200


@pytest.fixture(autouse=True)
def authorized_speech_contract(monkeypatch):
    monkeypatch.setattr(asr, "authorize_voice", AsyncMock(return_value=uuid4()))
