"""Tests for AI4Bharat ASR provider."""
import io
import wave

import pytest

pytest.importorskip("torch")
np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")

from app.asr.ai4bharat_provider import AI4BharatASRProvider  # noqa: E402


@pytest.mark.asyncio
async def test_ai4bharat_preprocess_audio():
    provider = AI4BharatASRProvider()
    # Create fake PCM audio
    samples = np.random.randn(16000).astype(np.float32)  # 1 second
    pcm = (samples * 32767).astype(np.int16).tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(pcm)
    audio_bytes = buffer.getvalue()
    tensor = provider._preprocess_audio(audio_bytes)
    assert tensor.shape[0] == 1  # mono
    assert tensor.shape[1] > 0


def test_ai4bharat_provider_name():
    provider = AI4BharatASRProvider()
    assert provider.provider_name == "ai4bharat"


def test_ai4bharat_lang_map():
    from app.asr.ai4bharat_provider import LANG_MAP
    assert "hi" in LANG_MAP
    assert "ta" in LANG_MAP
    assert "en" not in LANG_MAP
