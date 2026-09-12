"""IndicF5 TTS end-to-end test.

Tests AI4Bharat IndicF5 synthesis across multiple Indian languages.
Saves WAV files to a local folder for manual listening.

Usage:
    python -m tools.test_indicf5_tts

Output WAV files are saved to: tools/tts_output/
"""

import asyncio
import io
import os
import pathlib
import sys
import time
import wave

# ensure app is importable
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("TTS_PROVIDER", "indicf5")

OUTPUT_DIR = pathlib.Path(__file__).parent / "tts_output"

# Clinical sentences for each language
TEST_SENTENCES = {
    "hi": [
        "आपको दर्द कहाँ हो रहा है?",
        "क्या आपको सांस लेने में तकलीफ है?",
        "कृपया अभी डॉक्टर को बुलाइए।",
        "आपका बुखार कब से है?",
    ],
    "en": [
        "Where exactly does it hurt?",
        "Are you having difficulty breathing?",
        "Please alert the clinical staff immediately.",
        "How long have you had this fever?",
    ],
    "ta": ["உங்களுக்கு வலி எங்கே உள்ளது?"],
    "te": ["మీకు నొప్పి ఎక్కడ ఉంది?"],
    "bn": ["আপনার ব্যথা কোথায় হচ্ছে?"],
    "mr": ["तुम्हाला वेदना कुठे होत आहे?"],
    "gu": ["તમને ક્યાં દુખાવો થઈ રહ્યો છે?"],
    "kn": ["ನಿಮಗೆ ನೋವು ಎಲ್ಲಿ ಆಗುತ್ತಿದೆ?"],
    "ml": ["നിങ്ങൾക്ക് വേദന എവിടെ ഉണ്ട്?"],
}


def _validate_wav(content: bytes) -> dict:
    buf = io.BytesIO(content)
    with wave.open(buf, "rb") as wf:
        return {
            "channels": wf.getnchannels(),
            "sample_width_bytes": wf.getsampwidth(),
            "framerate_hz": wf.getframerate(),
            "n_frames": wf.getnframes(),
            "duration_s": round(wf.getnframes() / wf.getframerate(), 2),
        }


async def run_tests() -> None:
    print()
    print("=" * 62)
    print("INDICF5 TTS END-TO-END TEST")
    print("=" * 62)
    print()

    # Install check
    try:
        import f5_tts  # noqa: F401
        print("f5-tts: installed OK")
    except ImportError:
        print("ERROR: f5-tts not installed. Run: pip install f5-tts")
        sys.exit(1)

    # Load provider
    print("Loading IndicF5 provider (downloads model on first run ~1.5GB)...")
    from app.tts.indicf5_provider import IndicF5TTSProvider
    provider = IndicF5TTSProvider()

    t_load = time.monotonic()
    await provider.warmup()
    load_ms = (time.monotonic() - t_load) * 1000
    print(f"Model loaded on {provider._device} in {load_ms:.0f} ms")
    print()

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Saving WAV files to: {OUTPUT_DIR}")
    print()

    results = []
    total_pass = 0
    total_fail = 0

    for lang, sentences in TEST_SENTENCES.items():
        print(f"--- Language: {lang} ---")
        for i, text in enumerate(sentences):
            t0 = time.monotonic()
            try:
                audio = await provider.synthesize(text=text, language=lang)
                lat_ms = (time.monotonic() - t0) * 1000

                meta = _validate_wav(audio.content)
                ok = (
                    len(audio.content) > 500
                    and audio.media_type == "audio/wav"
                    and meta["n_frames"] > 0
                    and meta["channels"] == 1
                )
                status = "PASS" if ok else "FAIL"
                if ok:
                    total_pass += 1
                else:
                    total_fail += 1

                # Save WAV
                fname = OUTPUT_DIR / f"{lang}_{i+1:02d}.wav"
                fname.write_bytes(audio.content)

                print(f"  [{status}] {text[:55]}")
                print(f"         latency={lat_ms:.0f}ms  duration={meta['duration_s']}s  "
                      f"{meta['framerate_hz']}Hz  {len(audio.content)//1024}KB -> {fname.name}")

                results.append({
                    "lang": lang, "text": text, "status": status,
                    "latency_ms": round(lat_ms), "duration_s": meta["duration_s"],
                    "file": str(fname),
                })

            except Exception as exc:
                total_fail += 1
                print(f"  [FAIL] {text[:55]}")
                print(f"         ERROR: {exc}")
                results.append({"lang": lang, "text": text, "status": "ERROR", "error": str(exc)})

        print()

    # Summary
    print("=" * 62)
    print("SUMMARY")
    print("=" * 62)
    print(f"Passed  : {total_pass}")
    print(f"Failed  : {total_fail}")
    print(f"Total   : {total_pass + total_fail}")
    if results:
        good = [r for r in results if r["status"] == "PASS"]
        if good:
            avg_lat = sum(r["latency_ms"] for r in good) / len(good)
            avg_dur = sum(r["duration_s"] for r in good) / len(good)
            print(f"Avg latency  : {avg_lat:.0f} ms")
            print(f"Avg duration : {avg_dur:.2f} s")
    print()
    print(f"WAV files saved to: {OUTPUT_DIR}")
    print("Open the WAV files to listen to the synthesised speech.")
    print("=" * 62)

    sys.exit(0 if total_fail == 0 else 1)


if __name__ == "__main__":
    asyncio.run(run_tests())
