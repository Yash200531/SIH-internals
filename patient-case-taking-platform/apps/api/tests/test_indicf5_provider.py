import asyncio
import io
import os
import sys
import types
import wave
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.routers import tts as tts_router
from app.tts.indicf5_provider import IndicF5TTSProvider, _torch_compile_disabled


class _FakeIndicF5Model:
    def __init__(self) -> None:
        self.device: str | None = None
        self.ema_model = object()
        self.vocoder = object()

    def to(self, device: str):
        self.device = device
        return self

    def eval(self):
        return self


def _configure_provider(monkeypatch: pytest.MonkeyPatch, reference_path: Path) -> None:
    monkeypatch.setattr(settings, "INDICF5_MODEL", "ai4bharat/IndicF5", raising=False)
    monkeypatch.setattr(settings, "INDICF5_MODEL_REVISION", "model-revision", raising=False)
    monkeypatch.setattr(settings, "INDICF5_DEVICE", "cpu", raising=False)
    monkeypatch.setattr(settings, "INDICF5_REFERENCE_AUDIO_PATH", "", raising=False)
    monkeypatch.setattr(settings, "INDICF5_LOCAL_FILES_ONLY", False, raising=False)
    monkeypatch.setattr(settings, "INDICF5_DISABLE_COMPILE", True, raising=False)
    monkeypatch.setattr(settings, "INDICF5_NFE_STEPS", 16, raising=False)
    monkeypatch.setattr(settings, "INDICF5_CACHE_ENTRIES", 32, raising=False)
    monkeypatch.setattr(settings, "HUGGINGFACE_TOKEN", "hf-test-token")
    reference_path.write_bytes(b"RIFF-test-reference")


def _install_fake_f5(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_f5 = types.ModuleType("f5_tts")
    fake_f5.__path__ = []
    fake_infer_package = types.ModuleType("f5_tts.infer")
    fake_infer_package.__path__ = []
    fake_utils = types.ModuleType("f5_tts.infer.utils_infer")
    fake_utils.infer_process = lambda *_args, **_kwargs: (
        [0.0, 0.25, -0.25, 0.0],
        24_000,
        None,
    )
    fake_utils.preprocess_ref_audio_text = lambda path, text, **_kwargs: (path, text)
    monkeypatch.setitem(sys.modules, "f5_tts", fake_f5)
    monkeypatch.setitem(sys.modules, "f5_tts.infer", fake_infer_package)
    monkeypatch.setitem(sys.modules, "f5_tts.infer.utils_infer", fake_utils)


def test_compile_override_preserves_wrapper_with_eager_backend() -> None:
    calls: list[tuple[object, str | None]] = []
    original = object()

    class FakeTorch:
        @staticmethod
        def compile(model, *, backend=None):
            calls.append((model, backend))
            return "wrapped"

    original_compile = FakeTorch.compile
    with _torch_compile_disabled(FakeTorch, disabled=True):
        assert FakeTorch.compile(original) == "wrapped"
    assert calls == [(original, "eager")]
    assert FakeTorch.compile is original_compile


def test_loads_official_transformers_model_and_pinned_reference(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("torch")
    reference_path = tmp_path / "PAN_F_HAPPY_00001.wav"
    _configure_provider(monkeypatch, reference_path)
    monkeypatch.setattr(settings, "INDICF5_LOCAL_FILES_ONLY", True)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    model = _FakeIndicF5Model()
    load_calls: list[tuple[str, dict]] = []
    download_calls: list[tuple[str, str, dict]] = []

    class FakeAutoModel:
        @staticmethod
        def from_pretrained(model_name: str, **kwargs):
            load_calls.append((model_name, kwargs))
            return model, {
                "missing_keys": [],
                "unexpected_keys": [],
                "mismatched_keys": [],
                "error_msgs": [],
            }

    fake_transformers = types.ModuleType("transformers")
    fake_transformers.AutoModel = FakeAutoModel
    fake_hub = types.ModuleType("huggingface_hub")
    fake_hub.constants = types.SimpleNamespace(HF_HUB_OFFLINE=False)

    def fake_download(*, repo_id: str, filename: str, **kwargs):
        download_calls.append((repo_id, filename, kwargs))
        return str(reference_path)

    fake_hub.hf_hub_download = fake_download
    _install_fake_f5(monkeypatch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    provider = IndicF5TTSProvider()
    provider._ensure_model()

    assert model.device == "cpu"
    assert load_calls == [
        (
            "ai4bharat/IndicF5",
            {
                "revision": "model-revision",
                "token": "hf-test-token",
                "trust_remote_code": True,
                "local_files_only": True,
                "output_loading_info": True,
            },
        )
    ]
    assert download_calls == [
        (
            "ai4bharat/IndicF5",
            "prompts/PAN_F_HAPPY_00001.wav",
            {
                "revision": "model-revision",
                "token": "hf-test-token",
                "local_files_only": True,
            },
        )
    ]
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert fake_hub.constants.HF_HUB_OFFLINE is True


def test_synthesis_uses_matching_official_reference_and_returns_24khz_wav(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    np = pytest.importorskip("numpy")
    reference_path = tmp_path / "reference.wav"
    reference_path.write_bytes(b"RIFF-test-reference")
    model = _FakeIndicF5Model()
    infer_calls: list[tuple[tuple, dict]] = []

    def fake_infer(*args, **kwargs):
        infer_calls.append((args, kwargs))
        return np.array([0.0, 0.25, -0.25, 0.0], dtype=np.float32), 24_000, None

    provider = IndicF5TTSProvider()
    provider._model = model
    provider._reference_audio_path = str(reference_path)
    provider._prepared_reference_audio_path = str(reference_path)
    provider._prepared_reference_text = "published reference text. "
    provider._infer_process = fake_infer
    provider._device = "cpu"
    monkeypatch.setattr(provider, "_ensure_model", lambda: None)
    monkeypatch.setattr(settings, "INDICF5_NFE_STEPS", 16)
    monkeypatch.setattr(settings, "INDICF5_CACHE_ENTRIES", 32)

    wav_bytes = provider._sync_synthesize("नमस्ते", "hi")
    cached_wav_bytes = provider._sync_synthesize("नमस्ते", "hi")

    assert cached_wav_bytes == wav_bytes
    assert len(infer_calls) == 1
    args, kwargs = infer_calls[0]
    assert args[:3] == (str(reference_path), "published reference text. ", "नमस्ते")
    assert args[3:] == (model.ema_model, model.vocoder)
    assert kwargs["nfe_step"] == 16
    assert kwargs["device"] == "cpu"
    with wave.open(io.BytesIO(wav_bytes), "rb") as audio:
        assert audio.getframerate() == 24_000
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getnframes() == 4


def test_missing_reference_audio_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("torch")
    missing = tmp_path / "missing.wav"
    _configure_provider(monkeypatch, missing)
    missing.unlink()

    class FakeAutoModel:
        @staticmethod
        def from_pretrained(*_args, **_kwargs):
            return _FakeIndicF5Model(), {
                "missing_keys": [],
                "unexpected_keys": [],
                "mismatched_keys": [],
                "error_msgs": [],
            }

    fake_transformers = types.ModuleType("transformers")
    fake_transformers.AutoModel = FakeAutoModel
    fake_hub = types.ModuleType("huggingface_hub")
    fake_hub.constants = types.SimpleNamespace(HF_HUB_OFFLINE=False)
    fake_hub.hf_hub_download = lambda **_kwargs: str(missing)
    _install_fake_f5(monkeypatch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    with pytest.raises(RuntimeError, match="reference audio"):
        IndicF5TTSProvider()._ensure_model()


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [(TimeoutError(), 504), (RuntimeError("model failed"), 503)],
)
def test_tts_route_returns_bounded_provider_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception, expected_status: int
) -> None:
    class BrokenProvider:
        async def synthesize(self, *, text: str, language: str):
            raise error

    monkeypatch.setattr(tts_router, "get_active_provider", lambda: BrokenProvider())
    app = FastAPI()
    app.include_router(tts_router.router)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/tts/synthesize",
        json={"text": "नमस्ते", "language": "hi", "voice": "calm"},
    )

    assert response.status_code == expected_status
    assert response.json()["detail"] in {
        "TTS synthesis timed out",
        "TTS synthesis failed",
    }


def test_tts_route_rejects_whitespace_only_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ValidatingProvider:
        async def synthesize(self, *, text: str, language: str):
            raise ValueError("Cannot synthesise empty text")

    monkeypatch.setattr(tts_router, "get_active_provider", lambda: ValidatingProvider())
    app = FastAPI()
    app.include_router(tts_router.router)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/tts/synthesize",
        json={"text": "   ", "language": "hi", "voice": "calm"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid TTS synthesis request"


def test_tts_route_times_out_a_slow_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    class SlowProvider:
        async def synthesize(self, *, text: str, language: str):
            await asyncio.sleep(1)

    monkeypatch.setattr(tts_router, "get_active_provider", lambda: SlowProvider())
    monkeypatch.setattr(settings, "TTS_SYNTHESIS_TIMEOUT_SECONDS", 0.01)
    app = FastAPI()
    app.include_router(tts_router.router)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/tts/synthesize",
        json={"text": "नमस्ते", "language": "hi", "voice": "calm"},
    )

    assert response.status_code == 504
    assert response.json()["detail"] == "TTS synthesis timed out"
