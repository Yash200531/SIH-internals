"""Verify English content after 30 seconds using the existing public ASR fixtures."""

import asyncio
import io
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from app.asr.whisper_provider import WhisperEnglishASRProvider
from tools.benchmark_asr import normalize, word_error_rate


async def verify() -> dict:
    corpus = Path(__file__).resolve().parents[1] / "benchmarks/english-indian-monsoon"
    prefix, rate = sf.read(corpus / "sample-01.wav", dtype="float32")
    tail, tail_rate = sf.read(corpus / "sample-02.wav", dtype="float32")
    if rate != tail_rate:
        raise RuntimeError("Fixtures must use the same sample rate")
    repeats = int(31 * rate / len(prefix)) + 1
    audio = np.concatenate([prefix] * repeats + [tail])
    buffer = io.BytesIO()
    sf.write(buffer, audio, rate, format="WAV", subtype="PCM_16")
    result = await WhisperEnglishASRProvider(device="cpu").transcribe_file(buffer.getvalue())
    reference = "i feel more positive and refreshed"
    tail_text = " ".join(normalize(result.text)[-len(normalize(reference)):])
    tail_wer = word_error_rate(reference, tail_text)
    # Engineering coverage check: a completely truncated tail must fail.
    # Report substitutions as errors rather than treating coverage as accuracy.
    if tail_wer > 0.25:
        raise RuntimeError(f"ASR missed the synthetic tail phrase: {tail_text!r}")
    return {
        "passed": True, "provider": result.provider,
        "tail_start_seconds": round(len(prefix) * repeats / rate, 3),
        "duration_seconds": round(len(audio) / rate, 3),
        "processing_ms": result.duration_ms,
        "tail_wer": tail_wer,
        "tail_hypothesis": tail_text,
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(verify())))
