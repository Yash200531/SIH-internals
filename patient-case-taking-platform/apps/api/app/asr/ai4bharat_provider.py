"""AI4Bharat Indic Conformer 600M ASR provider.
Supports 22 Indian languages via HuggingFace transformers.

Model: ai4bharat/indic-conformer-600m-multilingual
Architecture: Multilingual Conformer CTC + RNNT
Languages: as, bn, brx, doi, gu, hi, kn, kok, ks, mai, ml, mni, mr, ne, or, pa, sa, sat, sd, ta, te, ur
"""
import asyncio
import io
import logging
import threading
import time
from typing import Any, AsyncIterator

import soundfile as sf
import torch

from app.asr.base import ASRProvider, TranscriptionChunk, TranscriptionResult
from app.config import settings

logger = logging.getLogger(__name__)

# Language code mapping (frontend code → model code)
LANG_MAP = {
    "hi": "hi",
    "bn": "bn", "ta": "ta", "te": "te", "mr": "mr",
    "gu": "gu", "kn": "kn", "ml": "ml", "pa": "pa",
    "or": "or", "as": "as", "ur": "ur", "ne": "ne",
}

MODEL_NAME = "ai4bharat/indic-conformer-600m-multilingual"
TARGET_SAMPLE_RATE = 16000


class AI4BharatASRProvider(ASRProvider):
    """AI4Bharat Indic Conformer ASR provider.

    Uses lazy loading — model loads on first transcription request.
    Supports CTC and RNNT decoding (RNNT is more accurate but slower).
    """

    def __init__(self, decoding: str = "rnnt", device: str | None = None):
        if decoding not in {"ctc", "rnnt"}:
            raise ValueError("ASR decoding must be either 'ctc' or 'rnnt'")
        self.decoding = decoding
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._model: Any | None = None
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    @property
    def provider_name(self) -> str:
        return "ai4bharat"

    def _ensure_model(self):
        """Lazy-load model on first use."""
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            try:
                logger.info("Loading AI4Bharat Indic Conformer model...")
                if self.device == "cuda":
                    import onnxruntime as ort

                    preload_dlls = getattr(ort, "preload_dlls", None)
                    if preload_dlls is not None:
                        preload_dlls()
                from transformers import AutoModel

                self._model = AutoModel.from_pretrained(
                    MODEL_NAME,
                    revision=settings.ASR_MODEL_REVISION,
                    token=settings.HUGGINGFACE_TOKEN or None,
                    trust_remote_code=True,
                ).to(self.device).eval()
                logger.info("Model loaded on %s", self.device)
            except Exception:
                logger.exception("Failed to load AI4Bharat model")
                raise

    def _preprocess_audio(self, audio_bytes: bytes, sample_rate: int = 16000) -> torch.Tensor:
        """Convert raw audio bytes to model input tensor."""
        try:
            audio_data, orig_sr = sf.read(io.BytesIO(audio_bytes))
        except Exception as exc:
            raise ValueError("Audio could not be decoded; send a valid WAV or supported container") from exc

        if audio_data.size == 0 or orig_sr <= 0:
            raise ValueError("Audio file is empty")

        if audio_data.ndim > 1:
            # Mix to mono
            audio_data = audio_data.mean(axis=1)

        # Resample if needed (simple linear interpolation — avoids torchaudio/FFmpeg dependency)
        if orig_sr != TARGET_SAMPLE_RATE:
            import numpy as np
            duration = len(audio_data) / orig_sr
            target_len = int(duration * TARGET_SAMPLE_RATE)
            indices = np.linspace(0, len(audio_data) - 1, target_len)
            audio_data = np.interp(indices, np.arange(len(audio_data)), audio_data)
        return torch.tensor(audio_data, dtype=torch.float32).unsqueeze(0)

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language: str = "hi",
        sample_rate: int = 16000,
    ) -> AsyncIterator[TranscriptionChunk]:
        """Stream transcription — collects all audio first, then transcribes.

        The Conformer model doesn't support true streaming, so we collect
        the full audio and return the result as a single final chunk.
        """
        # Collect all audio
        audio_chunks = []
        async for audio_chunk in audio_stream:
            audio_chunks.append(audio_chunk)

        if not audio_chunks:
            yield TranscriptionChunk(text="", confidence=0.0, is_final=True, language=language)
            return

        # Concatenate and transcribe
        result = await self.transcribe_file(b"".join(audio_chunks), language, sample_rate)
        for transcription_chunk in result.chunks:
            yield transcription_chunk

    async def transcribe_file(
        self,
        audio_bytes: bytes,
        language: str = "hi",
        sample_rate: int = 16000,
    ) -> TranscriptionResult:
        """Transcribe a complete audio file."""
        if not audio_bytes:
            raise ValueError("Audio file is empty")
        if language not in LANG_MAP:
            supported = ", ".join(sorted(LANG_MAP))
            raise ValueError(f"Unsupported ASR language '{language}'. Supported: {supported}")
        lang_code = LANG_MAP[language]

        start_time = time.time()
        await asyncio.to_thread(self._ensure_model)
        text = await asyncio.to_thread(self._sync_transcribe, audio_bytes, lang_code)

        duration_ms = int((time.time() - start_time) * 1000)

        return TranscriptionResult(
            text=text,
            confidence=None,
            language=language,
            chunks=[TranscriptionChunk(text=text, confidence=None, is_final=True, language=language)],
            duration_ms=duration_ms,
            provider="ai4bharat",
        )

    def _sync_transcribe(self, audio_bytes: bytes, language: str) -> str:
        """Synchronous transcription (runs in thread)."""
        tensor = self._preprocess_audio(audio_bytes)
        model = self._model
        if model is None:
            raise RuntimeError("ASR model is not initialized")

        with self._inference_lock, torch.inference_mode():
            result = model(tensor, language, self.decoding)

        # Model returns string directly
        if isinstance(result, str):
            return result.strip()
        elif isinstance(result, dict) and "text" in result:
            return result["text"].strip()
        else:
            return str(result).strip()

    async def warmup(self) -> None:
        """Load weights and initialize the selected ONNX decoding graph."""
        await asyncio.to_thread(self._ensure_model)
        await asyncio.to_thread(self._sync_warmup)

    def _sync_warmup(self) -> None:
        model = self._model
        if model is None:
            raise RuntimeError("ASR model is not initialized")
        with self._inference_lock, torch.inference_mode():
            model(torch.zeros((1, TARGET_SAMPLE_RATE)), "hi", self.decoding)

    async def detect_language(self, audio_bytes: bytes) -> str:
        """Detect language — default to Hindi for Indic model."""
        # Indic Conformer doesn't have built-in language detection
        # Default to Hindi; in production, use a separate detector
        return "hi"
