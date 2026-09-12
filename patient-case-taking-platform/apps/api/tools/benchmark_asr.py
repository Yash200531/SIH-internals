"""ASR Benchmark Tool — WER, CER, and latency evaluation.

Measures Word Error Rate (WER), Character Error Rate (CER), and inference
latency for the AI4Bharat and Whisper ASR providers against a manifest of
audio files with reference transcripts.

Usage:
    python tools/benchmark_asr.py --manifest path/to/manifest.jsonl \\
        --provider ai4bharat \\
        --language hi \\
        --output results/asr_benchmark.csv

Manifest format (one JSON object per line):
    {"audio": "path/to/file.wav", "reference": "expected transcript text", "language": "hi"}

Supported providers:
    ai4bharat   — Indic Conformer 600M (Hindi + 21 other Indian languages)
    whisper     — Whisper small.en (English only)
    mock        — Mock provider (for pipeline testing only, WER will be 100%)

Requirements:
    pip install -e ".[dev,ai-asr,eval]"
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import re
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Text normalisation and metric helpers (used by tests directly)
# ---------------------------------------------------------------------------

def normalize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace.

    Handles Hindi Devanagari punctuation (।) and ASCII punctuation.
    Returns a list of tokens, not a joined string.
    """
    text = text.lower()
    # Remove Hindi danda, double danda, and standard ASCII punctuation
    text = re.sub(r"[।॥!?,.\-:;\"'()\[\]{}]", " ", text)
    return [t for t in text.split() if t]


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Compute Word Error Rate using dynamic programming.

    WER = (S + D + I) / N  where N = number of reference words.
    Returns 0.0 for empty reference with empty hypothesis, 1.0 if
    reference is empty and hypothesis is not.
    """
    ref_tokens = normalize(reference)
    hyp_tokens = normalize(hypothesis)

    if not ref_tokens:
        return 0.0 if not hyp_tokens else 1.0

    # Levenshtein distance at word level
    r, h = len(ref_tokens), len(hyp_tokens)
    dp = list(range(h + 1))
    for i in range(1, r + 1):
        new_dp = [i] + [0] * h
        for j in range(1, h + 1):
            if ref_tokens[i - 1] == hyp_tokens[j - 1]:
                new_dp[j] = dp[j - 1]
            else:
                new_dp[j] = 1 + min(dp[j], new_dp[j - 1], dp[j - 1])
        dp = new_dp
    return dp[h] / r


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Compute Character Error Rate on normalised text."""
    ref = " ".join(normalize(reference))
    hyp = " ".join(normalize(hypothesis))
    if not ref:
        return 0.0 if not hyp else 1.0
    r, h = len(ref), len(hyp)
    dp = list(range(h + 1))
    for i in range(1, r + 1):
        new_dp = [i] + [0] * h
        for j in range(1, h + 1):
            if ref[i - 1] == hyp[j - 1]:
                new_dp[j] = dp[j - 1]
            else:
                new_dp[j] = 1 + min(dp[j], new_dp[j - 1], dp[j - 1])
        dp = new_dp
    return dp[h] / r


def nearest_rank_percentile(values: list[float], percentile: float) -> float:
    """Nearest-rank percentile (p90, p95 etc.) on a sorted list.

    percentile: 0.0–1.0  (e.g. 0.90 for P90)
    """
    if not values:
        raise ValueError("Cannot compute percentile of empty list")
    sorted_vals = sorted(values)
    # Nearest rank: ceil(p * N), clamped to [1, N]
    rank = max(1, min(len(sorted_vals), int(len(sorted_vals) * percentile + 0.9999)))
    return sorted_vals[rank - 1]


def _load_manifest(manifest_path: str) -> list[dict]:
    """Load a JSONL manifest file."""
    records = []
    with open(manifest_path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning("Skipping line %d (invalid JSON): %s", lineno, e)
    return records


def _build_provider(provider_name: str, language: str):
    """Build and return the requested ASR provider."""
    if provider_name == "mock":
        from app.asr.mock_provider import MockASRProvider
        return MockASRProvider()

    if provider_name == "ai4bharat":
        try:
            from app.asr.ai4bharat_provider import AI4BharatASRProvider
        except ImportError as e:
            print(f"Cannot import AI4Bharat provider: {e}", file=sys.stderr)
            print("Install: pip install -e '.[ai-asr]'", file=sys.stderr)
            sys.exit(1)
        return AI4BharatASRProvider(decoding="ctc")  # CTC is faster for benchmarking

    if provider_name == "whisper":
        if language != "en":
            print("Whisper provider only supports language='en'", file=sys.stderr)
            sys.exit(1)
        try:
            from app.asr.whisper_provider import WhisperEnglishASRProvider
        except ImportError as e:
            print(f"Cannot import Whisper provider: {e}", file=sys.stderr)
            print("Install: pip install -e '.[ai-asr]'", file=sys.stderr)
            sys.exit(1)
        return WhisperEnglishASRProvider()

    print(f"Unknown provider: {provider_name}. Use: ai4bharat, whisper, mock", file=sys.stderr)
    sys.exit(1)


async def _transcribe_one(
    provider, audio_path: str, language: str
) -> tuple[str, float]:
    """Transcribe a single audio file. Returns (transcript, latency_ms)."""
    audio_bytes = Path(audio_path).read_bytes()
    start = time.monotonic()
    result = await provider.transcribe_file(audio_bytes, language=language)
    latency_ms = (time.monotonic() - start) * 1000
    return result.text, latency_ms


def _compute_metrics(reference: str, hypothesis: str) -> dict[str, float]:
    """Compute WER and CER — uses jiwer if installed, falls back to built-in."""
    try:
        import jiwer  # type: ignore[import]
        ref = " ".join(normalize(reference))
        hyp = " ".join(normalize(hypothesis))
        if not ref:
            return {"wer": 0.0 if not hyp else 1.0, "cer": 0.0 if not hyp else 1.0}
        return {
            "wer": round(jiwer.wer(ref, hyp), 4),
            "cer": round(jiwer.cer(ref, hyp), 4),
        }
    except ImportError:
        return {
            "wer": round(word_error_rate(reference, hypothesis), 4),
            "cer": round(character_error_rate(reference, hypothesis), 4),
        }


async def run_benchmark(
    manifest_path: str,
    provider_name: str,
    language: str,
    output_path: str | None,
    warmup: bool,
) -> None:
    records = _load_manifest(manifest_path)
    if not records:
        logger.error("Manifest is empty: %s", manifest_path)
        sys.exit(1)

    logger.info("Loaded %d records from manifest", len(records))
    provider = _build_provider(provider_name, language)

    if warmup:
        logger.info("Warming up provider …")
        warmup_fn = getattr(provider, "warmup", None)
        if warmup_fn:
            await warmup_fn()

    rows: list[dict] = []
    wers, cers, latencies = [], [], []

    for i, record in enumerate(records):
        audio_path = record.get("audio", "")
        reference = record.get("reference", "")
        lang = record.get("language", language)

        if not Path(audio_path).exists():
            logger.warning("[%d/%d] Audio file not found: %s — skipping", i + 1, len(records), audio_path)
            continue

        logger.info("[%d/%d] %s", i + 1, len(records), audio_path)
        try:
            hypothesis, latency_ms = await _transcribe_one(provider, audio_path, lang)
        except Exception as exc:
            logger.error("[%d/%d] Transcription failed: %s", i + 1, len(records), exc)
            hypothesis = ""
            latency_ms = -1.0

        metrics = _compute_metrics(reference, hypothesis)
        row = {
            "file": audio_path,
            "language": lang,
            "reference": reference,
            "hypothesis": hypothesis,
            "wer": metrics["wer"],
            "cer": metrics["cer"],
            "latency_ms": round(latency_ms, 1),
            "provider": provider_name,
        }
        rows.append(row)
        if latency_ms > 0:
            wers.append(metrics["wer"])
            cers.append(metrics["cer"])
            latencies.append(latency_ms)

        logger.info(
            "  WER=%.2f%%  CER=%.2f%%  latency=%.0f ms",
            metrics["wer"] * 100,
            metrics["cer"] * 100,
            latency_ms,
        )

    # Summary
    if wers:
        avg_wer = sum(wers) / len(wers)
        avg_cer = sum(cers) / len(cers)
        avg_lat = sum(latencies) / len(latencies)
        p90_lat = sorted(latencies)[int(len(latencies) * 0.9)]
        print("\n" + "=" * 60)
        print(f"Provider  : {provider_name}")
        print(f"Language  : {language}")
        print(f"Samples   : {len(wers)} / {len(records)}")
        print(f"Avg WER   : {avg_wer * 100:.2f}%")
        print(f"Avg CER   : {avg_cer * 100:.2f}%")
        print(f"Avg lat   : {avg_lat:.0f} ms")
        print(f"P90 lat   : {p90_lat:.0f} ms")
        print("=" * 60)
    else:
        print("No successful transcriptions — check audio paths and provider setup.")

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["file", "language", "reference", "hypothesis",
                             "wer", "cer", "latency_ms", "provider"],
            )
            writer.writeheader()
            writer.writerows(rows)
        logger.info("Results saved to %s", output_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark ASR providers: WER, CER, and latency"
    )
    parser.add_argument(
        "--manifest", required=True,
        help="Path to a JSONL manifest file with 'audio', 'reference', 'language' fields"
    )
    parser.add_argument(
        "--provider", default="ai4bharat",
        choices=["ai4bharat", "whisper", "mock"],
        help="ASR provider to benchmark (default: ai4bharat)"
    )
    parser.add_argument(
        "--language", default="hi",
        help="Language code to use when manifest entries don't specify one (default: hi)"
    )
    parser.add_argument(
        "--output", default=None,
        help="CSV file path to save per-sample results (optional)"
    )
    parser.add_argument(
        "--no-warmup", action="store_true",
        help="Skip model warmup (first sample will include load time)"
    )
    args = parser.parse_args()

    # Add the api root to the path so app imports resolve
    api_root = Path(__file__).resolve().parent.parent
    if str(api_root) not in sys.path:
        sys.path.insert(0, str(api_root))

    asyncio.run(
        run_benchmark(
            manifest_path=args.manifest,
            provider_name=args.provider,
            language=args.language,
            output_path=args.output,
            warmup=not args.no_warmup,
        )
    )


if __name__ == "__main__":
    main()
