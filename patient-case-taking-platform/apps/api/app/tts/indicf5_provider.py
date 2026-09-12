"""Local AI4Bharat IndicF5 text-to-speech provider.

IndicF5 is distributed as a Hugging Face custom ``AutoModel``. It is not a
drop-in checkpoint for the public ``f5-tts`` API: the model's custom forward
method accepts generated text plus a matching reference WAV and transcript.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import threading
import wave
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from app.config import settings
from app.tts.base import SpeechAudio

logger = logging.getLogger(__name__)

_PROVIDER_NAME = "indicf5"
_PROVIDER_VERSION = "ai4bharat-IndicF5-v1"
_MODEL_REPO = "ai4bharat/IndicF5"
_MODEL_REVISION = "ba85abedf18dc479a447eaa0eccbd76ab78a47d5"
_REFERENCE_AUDIO_FILE = "prompts/PAN_F_HAPPY_00001.wav"
_REFERENCE_TEXT = (
    "ਭਹੰਪੀ ਵਿੱਚ ਸਮਾਰਕਾਂ ਦੇ ਭਵਨ ਨਿਰਮਾਣ ਕਲਾ ਦੇ ਵੇਰਵੇ ਗੁੰਝਲਦਾਰ ਅਤੇ ਹੈਰਾਨ ਕਰਨ ਵਾਲੇ ਹਨ, ਜੋ ਮੈਨੂੰ ਖੁਸ਼ ਕਰਦੇ  ਹਨ।"
)
_TARGET_SAMPLE_RATE = 24_000
_TARGET_RMS = 0.1
_SUPPORTED_APP_LANGUAGES = frozenset({"hi", "en"})


@contextmanager
def _torch_compile_disabled(torch: Any, *, disabled: bool) -> Iterator[None]:
    """Keep compile-compatible parameter names while using the eager backend.

    The published checkpoint stores acoustic-model keys below ``_orig_mod``.
    Returning the module unchanged would therefore prevent all trained weights
    from loading. PyTorch's eager compile backend preserves the wrapper/key
    layout without invoking the slow or unavailable Inductor/Triton path.
    """

    if not disabled or not hasattr(torch, "compile"):
        yield
        return

    original_compile = torch.compile
    torch.compile = lambda model, *_args, **_kwargs: original_compile(model, backend="eager")
    try:
        yield
    finally:
        torch.compile = original_compile


class IndicF5TTSProvider:
    """AI4Bharat IndicF5 using its supported Transformers custom-model API."""

    name = _PROVIDER_NAME
    version = _PROVIDER_VERSION

    def __init__(self) -> None:
        self._model: Any | None = None
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()
        self._device: str | None = None
        self._reference_audio_path: str | None = None
        self._prepared_reference_audio_path: str | None = None
        self._prepared_reference_text: str | None = None
        self._infer_process: Callable[..., tuple[Any, int, Any]] | None = None
        self._audio_cache: OrderedDict[tuple[str, str], bytes] = OrderedDict()

    async def synthesize(self, *, text: str, language: str) -> SpeechAudio:
        text = text.strip()
        if not text:
            raise ValueError("Cannot synthesise empty text")
        if language not in _SUPPORTED_APP_LANGUAGES:
            raise ValueError(f"IndicF5 does not support application language '{language}'")
        if language == "en":
            logger.warning(
                "IndicF5 officially supports 11 Indian languages; English output is best-effort"
            )

        wav_bytes = await asyncio.to_thread(self._sync_synthesize, text, language)
        return SpeechAudio(
            content=wav_bytes,
            media_type="audio/wav",
            provider=_PROVIDER_NAME,
            provider_version=_PROVIDER_VERSION,
        )

    async def warmup(self) -> None:
        """Load every artifact before the API reports ready."""

        await asyncio.to_thread(self._ensure_model)
        logger.info("IndicF5 warmup complete on %s", self._device)

    def _ensure_model(self) -> None:
        if self._model is not None:
            return

        with self._load_lock:
            if self._model is not None:
                return

            model_repo = settings.INDICF5_MODEL or _MODEL_REPO
            revision = settings.INDICF5_MODEL_REVISION or _MODEL_REVISION
            token = settings.HUGGINGFACE_TOKEN or None
            local_only = settings.INDICF5_LOCAL_FILES_ONLY
            if local_only:
                # The pinned custom model loads its vocoder and vocabulary through
                # nested Hub calls which do not receive local_files_only.
                os.environ["HF_HUB_OFFLINE"] = "1"

            try:
                import torch
                from f5_tts.infer.utils_infer import (
                    infer_process,
                    preprocess_ref_audio_text,
                )
                from huggingface_hub import constants as hub_constants
                from huggingface_hub import hf_hub_download
                from transformers import AutoModel
            except ImportError as exc:
                raise RuntimeError(
                    "IndicF5 dependencies are not installed; install the ai-tts-f5 extra"
                ) from exc

            if local_only:
                hub_constants.HF_HUB_OFFLINE = True

            requested_device = settings.INDICF5_DEVICE.strip().lower()
            if requested_device not in {"", "cpu", "cuda"}:
                raise RuntimeError("INDICF5_DEVICE must be empty, 'cpu', or 'cuda'")
            if requested_device == "cuda" and not torch.cuda.is_available():
                raise RuntimeError(
                    "INDICF5_DEVICE=cuda was requested, but CUDA-enabled PyTorch is unavailable"
                )
            device = requested_device or ("cuda" if torch.cuda.is_available() else "cpu")

            nfe_steps = settings.INDICF5_NFE_STEPS
            if not 8 <= nfe_steps <= 32:
                raise RuntimeError("INDICF5_NFE_STEPS must be between 8 and 32")
            if settings.INDICF5_CACHE_ENTRIES < 0:
                raise RuntimeError("INDICF5_CACHE_ENTRIES cannot be negative")

            configured_reference = settings.INDICF5_REFERENCE_AUDIO_PATH.strip()
            if configured_reference:
                reference_path = Path(configured_reference).expanduser().resolve()
            else:
                reference_path = Path(
                    hf_hub_download(
                        repo_id=model_repo,
                        filename=_REFERENCE_AUDIO_FILE,
                        revision=revision,
                        token=token,
                        local_files_only=local_only,
                    )
                )
            if not reference_path.is_file():
                raise RuntimeError(f"IndicF5 reference audio was not found: {reference_path}")

            logger.info(
                "Loading IndicF5 from %s at revision %s on %s",
                model_repo,
                revision,
                device,
            )
            prepared_reference_path: str | None = None
            try:
                with _torch_compile_disabled(torch, disabled=settings.INDICF5_DISABLE_COMPILE):
                    model, loading_info = AutoModel.from_pretrained(
                        model_repo,
                        revision=revision,
                        token=token,
                        trust_remote_code=True,
                        local_files_only=local_only,
                        output_loading_info=True,
                    )
                load_errors = {
                    key: loading_info.get(key, [])
                    for key in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")
                    if loading_info.get(key)
                }
                if load_errors:
                    logger.error("IndicF5 checkpoint did not load cleanly: %s", load_errors)
                    raise RuntimeError("IndicF5 checkpoint did not load cleanly")
                model = model.to(device)
                model.eval()
                if not hasattr(model, "ema_model") or not hasattr(model, "vocoder"):
                    raise RuntimeError("IndicF5 model does not expose its inference modules")
                prepared_reference_path, prepared_reference_text = preprocess_ref_audio_text(
                    str(reference_path),
                    _REFERENCE_TEXT,
                    show_info=logger.debug,
                    device=device,
                )
            except Exception as exc:
                if prepared_reference_path:
                    _remove_prepared_reference(prepared_reference_path, reference_path)
                logger.exception("IndicF5 model loading failed")
                raise RuntimeError("IndicF5 model loading failed") from exc

            self._device = device
            self._reference_audio_path = str(reference_path)
            self._prepared_reference_audio_path = prepared_reference_path
            self._prepared_reference_text = prepared_reference_text
            self._infer_process = infer_process
            self._model = model
            logger.info("IndicF5 loaded on %s with %s diffusion steps", device, nfe_steps)

    def _sync_synthesize(self, text: str, language: str) -> bytes:
        self._ensure_model()
        model = self._model
        prepared_audio_path = self._prepared_reference_audio_path
        prepared_text = self._prepared_reference_text
        infer_process = self._infer_process
        if (
            model is None
            or prepared_audio_path is None
            or prepared_text is None
            or infer_process is None
        ):
            raise RuntimeError("IndicF5 model is not initialised")

        cache_key = (language, text)
        with self._inference_lock:
            cached = self._audio_cache.get(cache_key)
            if cached is not None:
                self._audio_cache.move_to_end(cache_key)
                return cached
            try:
                audio, sample_rate, _ = infer_process(
                    prepared_audio_path,
                    prepared_text,
                    text,
                    model.ema_model,
                    model.vocoder,
                    mel_spec_type="vocos",
                    show_info=logger.debug,
                    nfe_step=settings.INDICF5_NFE_STEPS,
                    speed=1.0,
                    device=self._device,
                )
            except Exception as exc:
                logger.exception("IndicF5 synthesis failed for language=%s", language)
                raise RuntimeError("IndicF5 synthesis failed") from exc

            wav_bytes = _numpy_to_wav(audio, sample_rate)
            cache_entries = settings.INDICF5_CACHE_ENTRIES
            if cache_entries > 0:
                self._audio_cache[cache_key] = wav_bytes
                self._audio_cache.move_to_end(cache_key)
                while len(self._audio_cache) > cache_entries:
                    self._audio_cache.popitem(last=False)
            return wav_bytes

    def unload(self) -> None:
        """Release model references so another local GPU component can run."""

        with self._load_lock:
            self._model = None
            prepared_reference = self._prepared_reference_audio_path
            reference = self._reference_audio_path
            self._reference_audio_path = None
            self._prepared_reference_audio_path = None
            self._prepared_reference_text = None
            self._infer_process = None
            self._audio_cache.clear()
            device = self._device
            self._device = None
        if prepared_reference and reference:
            _remove_prepared_reference(prepared_reference, Path(reference))
        if device == "cuda":
            try:
                import torch

                torch.cuda.empty_cache()
            except ImportError:
                pass


def _numpy_to_wav(audio: Any, sample_rate: int) -> bytes:
    """Convert model output to a non-empty 16-bit mono WAV payload."""

    import numpy as np

    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()
    array = np.asarray(audio).squeeze()
    if array.ndim != 1 or array.size == 0:
        raise RuntimeError("IndicF5 returned empty or invalid audio")

    if np.issubdtype(array.dtype, np.integer):
        info = np.iinfo(array.dtype)
        float_audio = array.astype(np.float32) / float(max(abs(info.min), info.max))
    else:
        float_audio = array.astype(np.float32)
    if not np.isfinite(float_audio).all():
        raise RuntimeError("IndicF5 returned non-finite audio samples")

    peak = float(np.abs(float_audio).max())
    rms = float(np.sqrt(np.mean(np.square(float_audio))))
    if peak == 0.0 or rms == 0.0:
        raise RuntimeError("IndicF5 returned silent audio")
    gain = min(_TARGET_RMS / rms, 0.99 / peak)
    float_audio = float_audio * gain
    pcm = (np.clip(float_audio, -1.0, 1.0) * 32767).astype(np.int16)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    return buffer.getvalue()


def _remove_prepared_reference(prepared_path: str, source_path: Path) -> None:
    prepared = Path(prepared_path)
    try:
        if prepared.resolve() != source_path.resolve():
            prepared.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove prepared IndicF5 reference audio: %s", prepared)
