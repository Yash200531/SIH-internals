"""ASR provider registry.
Swap providers by changing the active provider."""
from app.asr.base import ASRProvider
from app.asr.mock_provider import MockASRProvider

_providers: dict[str, ASRProvider] = {}
_active: ASRProvider | None = None


def register_provider(name: str, provider: ASRProvider):
    _providers[name] = provider


def set_active_provider(name: str):
    global _active
    if name not in _providers:
        raise ValueError(f"Unknown ASR provider: {name}")
    _active = _providers[name]


def get_active_provider() -> ASRProvider:
    global _active
    if _active is not None:
        return _active

    from app.config import settings

    if settings.ASR_PROVIDER == "ai4bharat" and "ai4bharat" not in _providers:
        try:
            from app.asr.ai4bharat_provider import AI4BharatASRProvider
        except ImportError as exc:
            raise RuntimeError("AI4Bharat ASR dependencies are not installed") from exc
        register_provider("ai4bharat", AI4BharatASRProvider(decoding=settings.ASR_DECODING))
    if settings.ASR_PROVIDER not in _providers:
        raise RuntimeError(f"Unknown ASR provider: {settings.ASR_PROVIDER}")
    _active = _providers[settings.ASR_PROVIDER]
    return _active


def get_provider_for_language(language: str) -> ASRProvider:
    """Resolve an explicit language pack without silently changing providers."""
    from app.config import settings

    if language not in {"hi", "en"}:
        raise ValueError(f"Unsupported ASR language: {language}")
    if language == "en" and settings.ASR_PROVIDER != "mock":
        if settings.ASR_ENGLISH_PROVIDER != "whisper":
            raise RuntimeError(
                f"Unknown English ASR provider: {settings.ASR_ENGLISH_PROVIDER}"
            )
        if "whisper_english" not in _providers:
            try:
                from app.asr.whisper_provider import WhisperEnglishASRProvider
            except ImportError as exc:
                raise RuntimeError("English ASR dependencies are not installed") from exc
            register_provider("whisper_english", WhisperEnglishASRProvider())
        return _providers["whisper_english"]
    return get_active_provider()


def list_providers() -> list[str]:
    return list(_providers.keys())


# Register default providers
register_provider("mock", MockASRProvider())
