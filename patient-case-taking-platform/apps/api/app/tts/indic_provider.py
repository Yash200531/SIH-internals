"""AI4Bharat Indic Parler-TTS provider.

Model: ai4bharat/indic-parler-tts
Supports 21 Indian languages including Hindi, Bengali, Tamil, Telugu, Kannada,
Malayalam, Gujarati, Marathi, Punjabi, Odia, Assamese, Urdu, and English.

Requirements (installed via the ai-tts optional group):
    pip install -e ".[ai-tts]"

Set in .env:
    TTS_PROVIDER=indic
    INDIC_TTS_MODEL=ai4bharat/indic-parler-tts   # default
    INDIC_TTS_DEVICE=                             # auto = cuda if available, else cpu

Access: The model is gated on HuggingFace. You must:
    1. Accept the terms at https://huggingface.co/ai4bharat/indic-parler-tts
    2. Set HUGGINGFACE_TOKEN in .env

The provider lazy-loads on first synthesis call.
Inference runs in a thread pool so it never blocks the async event loop.
Output is 16-kHz mono WAV.

Speaker description prompts are language-specific to produce natural prosody.
"""

from __future__ import annotations

import asyncio
import io
import logging
import threading
import wave
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

from app.config import settings
from app.tts.base import SpeechAudio

logger = logging.getLogger(__name__)

_PROVIDER_NAME = "indic"
_PROVIDER_VERSION = "ai4bharat-indic-parler-tts-v1"
_TARGET_SAMPLE_RATE = 16_000

# Language-specific speaker description prompts that Parler-TTS uses
# to condition prosody. These are natural-language descriptions, not IDs.
_SPEAKER_DESCRIPTIONS: dict[str, str] = {
    "hi": "A female speaker with a clear, calm, and natural Hindi voice, moderate pace, no background noise.",
    "en": "A female speaker with a clear, natural English voice, moderate pace, no background noise.",
    "bn": "A female speaker with a clear and natural Bengali voice, moderate pace.",
    "ta": "A female speaker with a clear Tamil voice, moderate speaking pace.",
    "te": "A female speaker with a clear Telugu voice, moderate speaking pace.",
    "mr": "A female speaker with a clear Marathi voice, moderate speaking pace.",
    "gu": "A female speaker with a clear Gujarati voice, moderate speaking pace.",
    "kn": "A female speaker with a clear Kannada voice, moderate speaking pace.",
    "ml": "A female speaker with a clear Malayalam voice, moderate speaking pace.",
    "pa": "A female speaker with a clear Punjabi voice, moderate speaking pace.",
    "or": "A female speaker with a clear Odia voice, moderate speaking pace.",
    "as": "A female speaker with a clear Assamese voice, moderate speaking pace.",
    "ur": "A female speaker with a clear Urdu voice, moderate speaking pace.",
}

# Languages supported by the indic-parler-tts model
_SUPPORTED_LANGUAGES = frozenset(_SPEAKER_DESCRIPTIONS.keys())


class IndicParlerTTSProvider:
    """AI4Bharat Indic Parler-TTS synthesis provider.

    Thread-safe via a per-instance inference lock. The model is loaded once
    and reused for all requests.
    """

    name = _PROVIDER_NAME
    version = _PROVIDER_VERSION

    def __init__(self) -> None:
        self._model: Any | None = None
        self._tokenizer: Any | None = None
        self._description_tokenizer: Any | None = None
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()
        self._device: str | None = None

    # ------------------------------------------------------------------
    # Public interface (async, matches TTSProvider Protocol)
    # ------------------------------------------------------------------

    async def synthesize(self, *, text: str, language: str) -> SpeechAudio:
        """Synthesise speech and return a 16-kHz mono WAV."""
        if not text.strip():
            raise ValueError("Cannot synthesise empty text")

        lang = language if language in _SUPPORTED_LANGUAGES else "hi"
        if language not in _SUPPORTED_LANGUAGES:
            logger.warning(
                "IndicTTS: unsupported language '%s', falling back to Hindi", language
            )

        wav_bytes = await asyncio.to_thread(self._sync_synthesize, text, lang)
        return SpeechAudio(
            content=wav_bytes,
            media_type="audio/wav",
            provider=_PROVIDER_NAME,
            provider_version=_PROVIDER_VERSION,
        )

    async def warmup(self) -> None:
        """Load model weights and run a silent warmup pass."""
        await asyncio.to_thread(self._ensure_model)
        await asyncio.to_thread(self._sync_synthesize, "नमस्ते", "hi")
        logger.info("IndicTTS warmup complete on %s", self._device)

    # ------------------------------------------------------------------
    # Lazy model loading
    # ------------------------------------------------------------------

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            try:
                import torch
                from parler_tts import ParlerTTSForConditionalGeneration  # type: ignore[import]
                from transformers import AutoTokenizer  # type: ignore[import]
            except ImportError as exc:
                raise RuntimeError(
                    "Parler-TTS and transformers are required for IndicTTS. "
                    "Run: pip install -e '.[ai-tts]'"
                ) from exc

            model_name = settings.INDIC_TTS_MODEL
            hf_token = settings.HUGGINGFACE_TOKEN or None
            device_override = settings.INDIC_TTS_DEVICE
            device = (
                device_override
                if device_override
                else ("cuda" if torch.cuda.is_available() else "cpu")
            )
            self._device = device

            logger.info("Loading Indic Parler-TTS from %s on %s …", model_name, device)

            dtype = torch.float16 if device == "cuda" else torch.float32

            self._model = (
                ParlerTTSForConditionalGeneration.from_pretrained(
                    model_name,
                    token=hf_token,
                    torch_dtype=dtype,
                )
                .to(device)
                .eval()
            )
            self._tokenizer = AutoTokenizer.from_pretrained(
                model_name, token=hf_token
            )
            self._description_tokenizer = AutoTokenizer.from_pretrained(
                model_name, token=hf_token
            )
            logger.info("Indic Parler-TTS loaded on %s", device)

    # ------------------------------------------------------------------
    # Synchronous synthesis (runs in thread pool)
    # ------------------------------------------------------------------

    def _sync_synthesize(self, text: str, language: str) -> bytes:
        self._ensure_model()

        import numpy as np
        import torch

        model = self._model
        tokenizer = self._tokenizer
        desc_tokenizer = self._description_tokenizer
        device = self._device

        if model is None or tokenizer is None or desc_tokenizer is None:
            raise RuntimeError("IndicTTS model is not initialised")

        description = _SPEAKER_DESCRIPTIONS.get(language, _SPEAKER_DESCRIPTIONS["hi"])

        # Tokenise description and text
        desc_inputs = desc_tokenizer(
            description,
            return_tensors="pt",
        ).to(device)

        text_inputs = tokenizer(
            text,
            return_tensors="pt",
        ).to(device)

        with self._inference_lock, torch.inference_mode():
            generation = model.generate(
                input_ids=desc_inputs.input_ids,
                attention_mask=desc_inputs.attention_mask,
                prompt_input_ids=text_inputs.input_ids,
                prompt_attention_mask=text_inputs.attention_mask,
            )

        # generation is a tensor of shape (1, T) in the model's sample rate
        audio_arr = generation.cpu().float().numpy().squeeze()
        model_sr = model.config.sampling_rate  # typically 44100 for Parler-TTS

        # Resample to 16 kHz for consistent downstream handling
        if model_sr != _TARGET_SAMPLE_RATE:
            audio_arr = _resample(audio_arr, model_sr, _TARGET_SAMPLE_RATE)

        # Normalise to int16 range
        if audio_arr.max() > 1.0 or audio_arr.min() < -1.0:
            audio_arr = audio_arr / max(abs(audio_arr.max()), abs(audio_arr.min()))
        pcm = (audio_arr * 32767).astype(np.int16)

        return _pcm_to_wav(pcm, _TARGET_SAMPLE_RATE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resample(audio: "np.ndarray", orig_sr: int, target_sr: int) -> "np.ndarray":
    """Linear interpolation resampler — avoids torchaudio/libsoundfile dependency."""
    import numpy as np
    duration = len(audio) / orig_sr
    target_len = int(duration * target_sr)
    indices = np.linspace(0, len(audio) - 1, target_len)
    return np.interp(indices, np.arange(len(audio)), audio)


def _pcm_to_wav(pcm: "np.ndarray", sample_rate: int) -> bytes:
    """Encode int16 PCM samples as a WAV byte string."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()
