"""Acoustic quality checks used before trusting an ASR transcript."""

from array import array
from dataclasses import asdict, dataclass
from math import log10, sqrt


@dataclass(frozen=True)
class SignalQuality:
    score: float
    snr_db: float
    rms: float
    clipping_ratio: float
    has_speech: bool

    def as_dict(self) -> dict[str, float | bool]:
        return asdict(self)


def analyze_pcm16(pcm: bytes, sample_rate: int = 16_000) -> SignalQuality:
    """Estimate speech usability without presenting it as model confidence."""
    if len(pcm) < 2:
        return SignalQuality(0.0, 0.0, 0.0, 0.0, False)

    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not samples:
        return SignalQuality(0.0, 0.0, 0.0, 0.0, False)

    normalized = [sample / 32768.0 for sample in samples]
    rms = sqrt(sum(sample * sample for sample in normalized) / len(normalized))
    clipping_ratio = sum(abs(sample) >= 0.98 for sample in normalized) / len(normalized)

    frame_size = max(1, sample_rate // 50)
    frame_rms = []
    for start in range(0, len(normalized), frame_size):
        frame = normalized[start : start + frame_size]
        if frame:
            frame_rms.append(sqrt(sum(sample * sample for sample in frame) / len(frame)))

    ordered = sorted(frame_rms)
    noise = ordered[max(0, int(len(ordered) * 0.2) - 1)] if ordered else 0.0
    speech = ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))] if ordered else 0.0
    snr_db = 20 * log10(max(speech, 1e-6) / max(noise, 1e-6))
    has_speech = rms >= 0.008 and speech >= 0.015

    snr_score = min(1.0, max(0.0, (snr_db - 3.0) / 17.0))
    level_score = min(1.0, max(0.0, (rms - 0.008) / 0.06))
    score = (0.65 * snr_score) + (0.35 * level_score)
    score *= max(0.0, 1.0 - min(1.0, clipping_ratio * 10))
    if not has_speech:
        score = 0.0

    return SignalQuality(
        score=round(score, 3),
        snr_db=round(snr_db, 2),
        rms=round(rms, 5),
        clipping_ratio=round(clipping_ratio, 5),
        has_speech=has_speech,
    )
