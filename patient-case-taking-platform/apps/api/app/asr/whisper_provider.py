"""English language-pack provider backed by Whisper."""

import asyncio
import io
import threading
import time
from typing import Any, AsyncIterator

import soundfile as sf
import torch

from app.asr.base import ASRProvider, TranscriptionChunk, TranscriptionResult
from app.config import settings

TARGET_SAMPLE_RATE = 16_000


class WhisperEnglishASRProvider(ASRProvider):
    def __init__(self, model_name: str | None = None, device: str | None = None):
        self.model_name = model_name or settings.ASR_ENGLISH_MODEL
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._model: Any | None = None
        self._processor: Any | None = None
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    @property
    def provider_name(self) -> str:
        return "whisper_english"

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor

            dtype = torch.float16 if self.device == "cuda" else torch.float32
            self._processor = AutoProcessor.from_pretrained(self.model_name)
            self._model = (
                AutoModelForSpeechSeq2Seq.from_pretrained(
                    self.model_name,
                    dtype=dtype,
                    low_cpu_mem_usage=True,
                )
                .to(self.device)
                .eval()
            )

    async def warmup(self) -> None:
        await asyncio.to_thread(self._ensure_model)

    async def transcribe_file(
        self,
        audio_bytes: bytes,
        language: str = "en",
        sample_rate: int = TARGET_SAMPLE_RATE,
    ) -> TranscriptionResult:
        if language != "en":
            raise ValueError("Whisper English language pack only supports 'en'")
        if not audio_bytes:
            raise ValueError("Audio file is empty")
        started = time.monotonic()
        await asyncio.to_thread(self._ensure_model)
        text = await asyncio.to_thread(self._sync_transcribe, audio_bytes)
        return TranscriptionResult(
            text=text,
            confidence=None,
            language="en",
            chunks=[TranscriptionChunk(text=text, confidence=None, is_final=True, language="en")],
            duration_ms=int((time.monotonic() - started) * 1000),
            provider=self.provider_name,
        )

    def _sync_transcribe(self, audio_bytes: bytes) -> str:
        audio, source_rate = sf.read(io.BytesIO(audio_bytes), dtype="float32")
        if audio.size == 0:
            raise ValueError("Audio file is empty")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if source_rate != TARGET_SAMPLE_RATE:
            import numpy as np

            target_length = int(len(audio) * TARGET_SAMPLE_RATE / source_rate)
            audio = np.interp(
                np.linspace(0, len(audio) - 1, target_length),
                np.arange(len(audio)),
                audio,
            )
        model = self._model
        processor = self._processor
        if model is None or processor is None:
            raise RuntimeError("Whisper model is not initialized")
        long_form = len(audio) > 30 * TARGET_SAMPLE_RATE
        features = processor(
            audio, sampling_rate=TARGET_SAMPLE_RATE, return_tensors="pt",
            truncation=False, return_attention_mask=True,
        )
        inputs = features.input_features.to(self.device, dtype=model.dtype)
        with self._inference_lock, torch.inference_mode():
            # The configured ``.en`` checkpoint is English-only. Passing the
            # multilingual language/task controls raises in Transformers 5.x.
            generation_options = {}
            if long_form:
                # Whisper's native long-form decoder requires timestamps and
                # all feature frames; the extractor otherwise truncates at 30s.
                generation_options = {
                    "return_timestamps": True,
                    "attention_mask": features.attention_mask.to(self.device),
                }
            generated = model.generate(inputs, **generation_options)
        return processor.batch_decode(generated, skip_special_tokens=True)[0].strip()

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language: str = "en",
        sample_rate: int = TARGET_SAMPLE_RATE,
    ) -> AsyncIterator[TranscriptionChunk]:
        chunks = [chunk async for chunk in audio_stream]
        result = await self.transcribe_file(b"".join(chunks), language, sample_rate)
        for chunk in result.chunks:
            yield chunk

    async def detect_language(self, audio_bytes: bytes) -> str:
        return "en"
