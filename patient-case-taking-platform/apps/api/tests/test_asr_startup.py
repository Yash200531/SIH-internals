"""Speech-only deployments must not require the separate OCR runtime."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.main import app, lifespan


def test_cuda_asr_preloads_onnx_dlls_before_loading_model(monkeypatch):
    pytest.importorskip("soundfile")
    pytest.importorskip("torch")
    from app.asr.ai4bharat_provider import AI4BharatASRProvider

    events: list[str] = []

    class FakeModel:
        def to(self, device):
            assert device == "cuda"
            return self

        def eval(self):
            return self

    class FakeAutoModel:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            events.append("load-model")
            return FakeModel()

    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        SimpleNamespace(preload_dlls=lambda: events.append("preload-dlls")),
    )
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(AutoModel=FakeAutoModel))

    provider = AI4BharatASRProvider(device="cuda")
    provider._ensure_model()

    assert events == ["preload-dlls", "load-model"]


@pytest.mark.asyncio
async def test_speech_warmup_loads_both_languages_without_ocr(monkeypatch):
    hindi = AsyncMock()
    english = AsyncMock()
    monkeypatch.setattr(settings, "ASR_PROVIDER", "ai4bharat")
    monkeypatch.setattr(settings, "MODEL_WARMUP_ON_START", False)
    monkeypatch.setattr(settings, "ASR_WARMUP_ON_START", True)
    monkeypatch.setattr("app.asr.registry.get_active_provider", lambda: hindi)

    def language_provider(language):
        assert language == "en"
        return english

    def unexpected_ocr():
        raise AssertionError("OCR belongs to the document worker")

    monkeypatch.setattr("app.asr.registry.get_provider_for_language", language_provider)
    monkeypatch.setattr("app.ocr.registry.get_active_provider", unexpected_ocr)
    async with lifespan(app):
        hindi.warmup.assert_awaited_once()
        english.warmup.assert_awaited_once()


@pytest.mark.asyncio
async def test_speech_warmup_failure_prevents_startup(monkeypatch):
    provider = AsyncMock()
    provider.warmup.side_effect = RuntimeError("model unavailable")
    monkeypatch.setattr(settings, "ASR_PROVIDER", "mock")
    monkeypatch.setattr(settings, "MODEL_WARMUP_ON_START", False)
    monkeypatch.setattr(settings, "ASR_WARMUP_ON_START", True)
    monkeypatch.setattr("app.asr.registry.get_active_provider", lambda: provider)
    with pytest.raises(RuntimeError, match="model unavailable"):
        async with lifespan(app):
            pytest.fail("Startup must fail when requested warmup fails")


@pytest.mark.asyncio
async def test_tts_warmup_loads_selected_provider_before_startup(monkeypatch):
    provider = AsyncMock()
    monkeypatch.setattr(settings, "MODEL_WARMUP_ON_START", False)
    monkeypatch.setattr(settings, "ASR_WARMUP_ON_START", False)
    monkeypatch.setattr(settings, "TTS_WARMUP_ON_START", True)
    monkeypatch.setattr("app.tts.registry.get_active_provider", lambda: provider)

    async with lifespan(app):
        provider.warmup.assert_awaited_once()
