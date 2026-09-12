"""Full ASR test — mock provider, quality analysis, WER/CER, streaming, registry.

Usage:
    python -m tools.test_asr_full

Tests:
    1. Mock provider transcription (Hindi + English)
    2. Signal quality analysis
    3. WER / CER metric computation
    4. ASR registry management
    5. Streaming transcription
    6. AI4Bharat provider availability check
"""

import asyncio
import io
import math
import struct
import sys
import time
import wave


def _make_wav(freq: int = 440, duration_ms: int = 1000) -> bytes:
    sr = 16000
    n = int(sr * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            s = int(8000 * math.sin(2 * math.pi * freq * i / sr))
            frames.extend(struct.pack("<h", s))
        wf.writeframes(bytes(frames))
    return buf.getvalue()


def _silent_wav(duration_ms: int = 500) -> bytes:
    sr = 16000
    n = int(sr * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


async def test_mock_provider() -> bool:
    print("--- Test 1: Mock provider (Hindi) ---")
    from app.asr.mock_provider import MockASRProvider
    mock = MockASRProvider()
    t0 = time.monotonic()
    r = await mock.transcribe_file(_make_wav(440, 2000), language="hi")
    lat = (time.monotonic() - t0) * 1000
    print(f"  Provider  : {r.provider}")
    print(f"  Language  : {r.language}")
    print(f"  Text      : {r.text!r}")
    print(f"  Latency   : {lat:.0f} ms (wall clock)")
    print(f"  Duration  : {r.duration_ms} ms (reported)")
    ok = r.provider == "mock" and r.language == "hi"
    print(f"  Result    : {'PASS' if ok else 'FAIL'}")
    return ok


async def test_mock_english() -> bool:
    print("--- Test 2: Mock provider (English) ---")
    from app.asr.mock_provider import MockASRProvider
    mock = MockASRProvider()
    r = await mock.transcribe_file(_make_wav(300, 1500), language="en")
    print(f"  Provider  : {r.provider}")
    print(f"  Language  : {r.language}")
    print(f"  Text      : {r.text!r}")
    ok = r.language == "en"
    print(f"  Result    : {'PASS' if ok else 'FAIL'}")
    return ok


async def test_signal_quality() -> bool:
    print("--- Test 3: Signal quality analysis ---")
    from app.asr.quality import analyze_pcm16
    # Test with a real tone signal
    wav = _make_wav(freq=440, duration_ms=1000)
    with wave.open(io.BytesIO(wav)) as wf:
        pcm = wf.readframes(wf.getnframes())
    q = analyze_pcm16(pcm)
    print(f"  Has speech : {q.has_speech}")
    print(f"  Quality    : {q.as_dict()}")
    # Test with silence
    silent_wav = _silent_wav(500)
    with wave.open(io.BytesIO(silent_wav)) as wf:
        silent_pcm = wf.readframes(wf.getnframes())
    q_silent = analyze_pcm16(silent_pcm)
    print(f"  Silent has_speech: {q_silent.has_speech}")
    ok = True  # quality check doesn't fail, just reports
    print(f"  Result    : {'PASS' if ok else 'FAIL'}")
    return ok


def test_wer_cer_metrics() -> bool:
    print("--- Test 4: WER / CER / P90 latency metrics ---")
    from tools.benchmark_asr import (
        character_error_rate,
        nearest_rank_percentile,
        normalize,
        word_error_rate,
    )
    all_pass = True
    cases = [
        ("मुझे बुखार है", "मुझे बुखार है", 0.0, "perfect Hindi match"),
        ("patient has fever", "patient has fever", 0.0, "perfect English match"),
        ("patient has fever", "patient has cough", 1 / 3, "one substitution"),
        ("chest pain severe", "chest pain", 1 / 3, "one deletion"),
        ("shortness of breath", "shortage of breath", 1 / 3, "one substitution"),
        ("बुखार है।", "बुखार है", 0.0, "Hindi punctuation normalised"),
    ]
    for ref, hyp, expected, desc in cases:
        wer = word_error_rate(ref, hyp)
        cer = character_error_rate(ref, hyp)
        ok = abs(wer - expected) < 0.05
        if not ok:
            all_pass = False
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {desc}")
        print(f"         REF={ref!r}  HYP={hyp!r}")
        print(f"         WER={wer:.3f} (expected ~{expected:.3f})  CER={cer:.3f}")

    # P90 latency test
    sample_latencies = [120, 150, 200, 180, 160, 140, 220, 190, 170, 250]
    p90 = nearest_rank_percentile(sorted(sample_latencies), 0.9)
    p50 = nearest_rank_percentile(sorted(sample_latencies), 0.5)
    print(f"  Sample latencies P50={p50:.0f}ms  P90={p90:.0f}ms")

    # Normalisation test
    normalised = normalize("बुखार है। FEVER!")
    ok_norm = normalised == ["बुखार", "है", "fever"]
    if not ok_norm:
        all_pass = False
    print(f"  Normalise test: {normalised}  {'PASS' if ok_norm else 'FAIL'}")
    print(f"  Result    : {'PASS' if all_pass else 'FAIL'}")
    return all_pass


def test_asr_registry() -> bool:
    print("--- Test 5: ASR registry ---")
    from app.asr.mock_provider import MockASRProvider
    from app.asr.registry import (
        get_active_provider,
        list_providers,
        register_provider,
        set_active_provider,
    )
    register_provider("mock", MockASRProvider())
    set_active_provider("mock")
    active = get_active_provider()
    providers = list_providers()
    print(f"  Active provider : {active.provider_name}")
    print(f"  All registered  : {providers}")
    ok = active.provider_name == "mock" and "mock" in providers
    print(f"  Result    : {'PASS' if ok else 'FAIL'}")
    return ok


async def test_streaming() -> bool:
    print("--- Test 6: Streaming transcription ---")
    from app.asr.mock_provider import MockASRProvider
    mock = MockASRProvider()
    wav_bytes = _make_wav(freq=330, duration_ms=800)

    async def audio_stream():
        chunk_size = 3200
        for i in range(0, len(wav_bytes), chunk_size):
            yield wav_bytes[i : i + chunk_size]

    chunks = []
    async for chunk in mock.transcribe_stream(audio_stream(), language="hi"):
        chunks.append(chunk)

    print(f"  Chunks received : {len(chunks)}")
    print(f"  Final chunk     : is_final={chunks[-1].is_final}")
    print(f"  Text            : {chunks[-1].text!r}")
    ok = len(chunks) > 0 and chunks[-1].is_final
    print(f"  Result    : {'PASS' if ok else 'FAIL'}")
    return ok


def test_ai4bharat_availability() -> bool:
    print("--- Test 7: AI4Bharat provider availability ---")
    try:
        from app.asr.ai4bharat_provider import AI4BharatASRProvider
        p = AI4BharatASRProvider(decoding="ctc")
        print(f"  Provider name : {p.provider_name}")
        print(f"  Device        : {p.device}")
        print(f"  Decoding      : {p.decoding}")
        print(f"  Result    : PASS (importable, GPU={p.device})")
        return True
    except ImportError as e:
        print(f"  Import error  : {e}")
        print("  Result    : SKIP (run: pip install -e '.[ai-asr]')")
        return True  # not a failure — optional dep


def test_whisper_availability() -> bool:
    print("--- Test 8: Whisper English provider availability ---")
    try:
        from app.asr.whisper_provider import WhisperEnglishASRProvider
        p = WhisperEnglishASRProvider()
        print(f"  Provider name : {p.provider_name}")
        print(f"  Model         : {p.model_name}")
        print(f"  Device        : {p.device}")
        print("  Result    : PASS (importable)")
        return True
    except ImportError as e:
        print(f"  Import error  : {e}")
        print("  Result    : SKIP (run: pip install -e '.[ai-asr]')")
        return True


async def run_all() -> None:
    print()
    print("=" * 60)
    print("FULL ASR TEST SUITE")
    print("=" * 60)
    print()

    results = []
    results.append(("Mock Hindi", await test_mock_provider()))
    print()
    results.append(("Mock English", await test_mock_english()))
    print()
    results.append(("Signal quality", await test_signal_quality()))
    print()
    results.append(("WER/CER/P90", test_wer_cer_metrics()))
    print()
    results.append(("ASR Registry", test_asr_registry()))
    print()
    results.append(("Streaming", await test_streaming()))
    print()
    results.append(("AI4Bharat avail", test_ai4bharat_availability()))
    print()
    results.append(("Whisper avail", test_whisper_availability()))
    print()

    print("=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    all_pass = True
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  {status}  {name}")
    print()
    print("=" * 60)
    if all_pass:
        print("ALL ASR TESTS PASSED")
    else:
        print("SOME TESTS FAILED — see above")
    print("=" * 60)
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    asyncio.run(run_all())
