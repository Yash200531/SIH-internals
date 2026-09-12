"""Tests for ASR abstraction and mock provider."""
import pytest

from app.asr.mock_provider import MockASRProvider
from app.asr.registry import (
    get_active_provider,
    get_provider_for_language,
    register_provider,
    set_active_provider,
)


@pytest.mark.asyncio
async def test_mock_transcribe_file():
    provider = MockASRProvider()
    result = await provider.transcribe_file(b"\x00" * 1000, language="hi")
    assert result.text
    assert result.confidence > 0
    assert result.language == "hi"
    assert result.provider == "mock"


@pytest.mark.asyncio
async def test_mock_transcribe_stream():
    provider = MockASRProvider()

    async def audio_gen():
        yield b"\x00" * 5000

    chunks = []
    async for chunk in provider.transcribe_stream(audio_gen(), language="en"):
        chunks.append(chunk)

    assert len(chunks) > 0
    assert chunks[-1].is_final is True


@pytest.mark.asyncio
async def test_mock_detect_language():
    provider = MockASRProvider()
    lang = await provider.detect_language(b"\x00" * 1000)
    assert lang in ("hi", "en")


def test_registry_default():
    provider = get_active_provider()
    assert provider.provider_name == "mock"


def test_registry_custom():
    custom = MockASRProvider(error_rate=0.5)
    register_provider("test", custom)
    set_active_provider("test")
    provider = get_active_provider()
    assert provider.provider_name == "mock"  # mock's name
    # Reset
    set_active_provider("mock")


def test_language_pack_uses_default_provider_in_mock_mode():
    assert get_provider_for_language("hi").provider_name == "mock"
    assert get_provider_for_language("en").provider_name == "mock"


def test_language_pack_rejects_unsupported_language():
    with pytest.raises(ValueError, match="Unsupported ASR language"):
        get_provider_for_language("fr")
