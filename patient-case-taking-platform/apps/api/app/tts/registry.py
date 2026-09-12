"""TTS provider registry.

Supported providers:
  mock    -- deterministic offline WAV tone (default, no model download)
  indic   -- AI4Bharat Indic Parler-TTS (21 Indian languages)
  indicf5 -- AI4Bharat IndicF5 (11 Indian languages, zero-shot voice cloning)

Set TTS_PROVIDER in .env to switch between them.
  indicf5 requires: pip install -e ".[ai-tts-f5]"
  indic   requires: pip install -e ".[ai-tts]"
  Both require HUGGINGFACE_TOKEN for gated model access.
"""

from app.config import settings
from app.tts.base import TTSProvider

_SUPPORTED = {"mock", "indic", "indicf5"}

_provider: TTSProvider | None = None


def get_active_provider() -> TTSProvider:
    global _provider
    # Re-check on every call so monkeypatching in tests takes effect
    if _provider is not None and _provider.name == settings.TTS_PROVIDER:
        return _provider

    name = settings.TTS_PROVIDER

    if name not in _SUPPORTED:
        raise RuntimeError(
            f"TTS provider '{name}' is not supported. "
            f"Supported providers: {', '.join(sorted(_SUPPORTED))}"
        )

    if name == "mock":
        from app.tts.mock_provider import MockTTSProvider

        _provider = MockTTSProvider()
        return _provider

    if name == "indic":
        from app.tts.indic_provider import IndicParlerTTSProvider

        _provider = IndicParlerTTSProvider()
        return _provider

    if name == "indicf5":
        from app.tts.indicf5_provider import IndicF5TTSProvider

        _provider = IndicF5TTSProvider()
        return _provider

    raise RuntimeError(f"Unhandled TTS provider: {name}")
