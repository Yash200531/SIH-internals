"""Protect against the feature extractor's default 30-second truncation."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
pytest.importorskip("soundfile")

from app.asr.whisper_provider import WhisperEnglishASRProvider  # noqa: E402


@pytest.mark.parametrize("seconds,long_form", [(2, False), (31, True)])
def test_full_audio_is_passed_to_decoder(monkeypatch, seconds, long_form):
    audio = np.zeros(seconds * 16000, dtype=np.float32)
    monkeypatch.setattr("app.asr.whisper_provider.sf.read", lambda *_a, **_k: (audio, 16000))
    features = SimpleNamespace(
        input_features=torch.zeros(1, 80, seconds * 100),
        attention_mask=torch.ones(1, seconds * 100),
    )
    processor = Mock(return_value=features)
    processor.batch_decode.return_value = ["Complete transcript"]
    model = Mock(dtype=torch.float32)
    provider = WhisperEnglishASRProvider(device="cpu")
    provider._model = model
    provider._processor = processor
    assert provider._sync_transcribe(b"synthetic") == "Complete transcript"
    assert processor.call_args.kwargs["truncation"] is False
    if long_form:
        assert model.generate.call_args.kwargs["return_timestamps"] is True
        assert model.generate.call_args.args[0].shape[-1] > 3000
    else:
        assert "return_timestamps" not in model.generate.call_args.kwargs
