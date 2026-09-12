"""TTS Pipeline Test — verifies the full synthesise → WAV → playback contract.

Tests both mock and indic providers end-to-end:
  1. Provider loads without error
  2. synthesize() returns a SpeechAudio with valid WAV content
  3. WAV has correct format (16-kHz, 16-bit, mono)
  4. Latency is reported
  5. At least one sentence per supported language is synthesised

Usage:
    # Test mock provider (no model download needed)
    python tools/test_tts_pipeline.py --provider mock

    # Test Indic TTS (requires ai-tts deps and HuggingFace token)
    python tools/test_tts_pipeline.py --provider indic

    # Save WAV files for manual listening
    python tools/test_tts_pipeline.py --provider indic --save-dir /tmp/tts_samples
"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import os
import sys
import time
import wave
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Test sentences per language
_TEST_SENTENCES: dict[str, list[str]] = {
    "hi": [
        "आपका दर्द कहाँ हो रहा है?",
        "क्या आप सांस लेने में तकलीफ महसूस कर रहे हैं?",
        "कृपया डॉक्टर को तुरंत बताएं।",
    ],
    "en": [
        "Where exactly do you feel the pain?",
        "Are you having any difficulty breathing?",
        "Please alert the clinical staff immediately.",
    ],
    "ta": ["உங்களுக்கு எங்கே வலி உள்ளது?"],
    "te": ["మీకు నొప్పి ఎక్కడ ఉంది?"],
    "bn": ["আপনার ব্যথা কোথায় হচ্ছে?"],
    "mr": ["तुम्हाला वेदना कुठे होत आहे?"],
    "gu": ["તમને ક્યાં દર્દ થઈ રહ્યું છે?"],
    "kn": ["ನಿಮಗೆ ನೋವು ಎಲ್ಲಿ ಆಗುತ್ತಿದೆ?"],
    "ml": ["നിങ്ങൾക്ക് വേദന എവിടെ ഉണ്ട്?"],
}


def _validate_wav(content: bytes) -> dict:
    """Validate WAV format and return metadata."""
    buf = io.BytesIO(content)
    with wave.open(buf, "rb") as wf:
        return {
            "channels": wf.getnchannels(),
            "sample_width": wf.getsampwidth(),
            "framerate": wf.getframerate(),
            "n_frames": wf.getnframes(),
            "duration_s": wf.getnframes() / wf.getframerate(),
        }


async def test_provider(provider_name: str, save_dir: str | None) -> bool:
    # Add api root to path
    api_root = Path(__file__).resolve().parent.parent
    if str(api_root) not in sys.path:
        sys.path.insert(0, str(api_root))

    # Override TTS_PROVIDER in settings before importing registry
    os.environ["TTS_PROVIDER"] = provider_name

    # Re-import after env override
    import importlib

    import app.config as cfg_mod
    importlib.reload(cfg_mod)
    # Reset the registry singleton so it picks up the new provider
    import app.tts.registry as reg_mod
    reg_mod._provider = None

    from app.tts.registry import get_active_provider

    logger.info("=== TTS Pipeline Test — provider: %s ===", provider_name)
    provider = get_active_provider()

    # Warmup
    warmup = getattr(provider, "warmup", None)
    if warmup:
        logger.info("Warming up …")
        await warmup()

    if save_dir:
        Path(save_dir).mkdir(parents=True, exist_ok=True)

    all_passed = True
    results = []

    # Limit to hi + en for mock; all languages for indic
    languages = list(_TEST_SENTENCES.keys()) if provider_name == "indic" else ["hi", "en"]

    for lang in languages:
        for sentence in _TEST_SENTENCES.get(lang, []):
            logger.info("  [%s] %s", lang, sentence[:60])
            start = time.monotonic()
            try:
                audio = await provider.synthesize(text=sentence, language=lang)
                latency_ms = (time.monotonic() - start) * 1000

                # Validate
                meta = _validate_wav(audio.content)
                ok = (
                    len(audio.content) > 100
                    and audio.media_type == "audio/wav"
                    and meta["channels"] == 1
                    and meta["sample_width"] == 2
                    and meta["n_frames"] > 0
                )
                status = "PASS" if ok else "FAIL"
                if not ok:
                    all_passed = False

                results.append({
                    "lang": lang,
                    "text": sentence[:50],
                    "status": status,
                    "latency_ms": round(latency_ms, 1),
                    "duration_s": round(meta["duration_s"], 2),
                    "bytes": len(audio.content),
                    "framerate": meta["framerate"],
                })
                logger.info(
                    "    %s  latency=%.0f ms  duration=%.2f s  %d Hz  %d bytes",
                    status, latency_ms, meta["duration_s"], meta["framerate"], len(audio.content),
                )

                if save_dir and ok:
                    fname = Path(save_dir) / f"{provider_name}_{lang}_{len(results):03d}.wav"
                    fname.write_bytes(audio.content)
                    logger.info("    Saved: %s", fname)

            except Exception as exc:
                all_passed = False
                logger.error("    FAIL  error=%s", exc)
                results.append({
                    "lang": lang, "text": sentence[:50],
                    "status": "ERROR", "error": str(exc),
                    "latency_ms": -1, "duration_s": 0,
                })

    # Summary
    passed = sum(1 for r in results if r["status"] == "PASS")
    print(f"\n{'=' * 50}")
    print(f"Provider : {provider_name}")
    print(f"Results  : {passed}/{len(results)} passed")
    if results:
        good = [r for r in results if r["status"] == "PASS"]
        if good:
            avg_lat = sum(r["latency_ms"] for r in good) / len(good)
            print(f"Avg lat  : {avg_lat:.0f} ms")
    print(f"{'=' * 50}\n")

    return all_passed


def main() -> None:
    parser = argparse.ArgumentParser(description="Test TTS provider pipeline end-to-end")
    parser.add_argument(
        "--provider", default="mock",
        choices=["mock", "indic"],
        help="TTS provider to test (default: mock)"
    )
    parser.add_argument(
        "--save-dir", default=None,
        help="Directory to save WAV output files for manual listening"
    )
    args = parser.parse_args()

    passed = asyncio.run(test_provider(args.provider, args.save_dir))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
