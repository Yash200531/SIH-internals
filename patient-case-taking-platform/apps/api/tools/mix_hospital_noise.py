"""Create a reproducible hospital-ambient-noise ASR evaluation set."""

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf


def _mono_16k(path: Path) -> np.ndarray:
    audio, rate = sf.read(path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate != 16_000:
        length = int(len(audio) * 16_000 / rate)
        audio = np.interp(np.linspace(0, len(audio) - 1, length), np.arange(len(audio)), audio)
    return audio


def mix_at_snr(speech: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    repeats = int(np.ceil(len(speech) / len(noise)))
    noise = np.tile(noise, repeats)[: len(speech)]
    speech_rms = np.sqrt(np.mean(np.square(speech)))
    noise_rms = np.sqrt(np.mean(np.square(noise)))
    target_noise_rms = speech_rms / (10 ** (snr_db / 20))
    mixed = speech + noise * (target_noise_rms / max(noise_rms, 1e-8))
    peak = np.max(np.abs(mixed))
    return mixed / max(1.0, peak / 0.98)


def build(source_manifest: Path, noise_dir: Path, output_dir: Path, snr_db: float) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    noise_files = sorted(noise_dir.glob("hospital-*.wav"))
    if not noise_files:
        raise ValueError("No hospital noise WAV files found")
    rows = [
        json.loads(line)
        for line in source_manifest.read_text(encoding="utf-8-sig").splitlines()
        if line
    ]
    output_rows = []
    for index, row in enumerate(rows):
        speech = _mono_16k(source_manifest.parent / row["audio"])
        noise = _mono_16k(noise_files[index % len(noise_files)])
        filename = f"{row['id']}-hospital-{snr_db:g}db.wav"
        sf.write(output_dir / filename, mix_at_snr(speech, noise, snr_db), 16_000, subtype="PCM_16")
        output_rows.append(
            {
                **row,
                "audio": filename,
                "condition": f"hospital_ambient_{snr_db:g}db",
                "noise_source": "m42-health/hospital_ambient_noise",
            }
        )
    manifest = output_dir / "manifest.jsonl"
    manifest.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in output_rows) + "\n",
        encoding="utf-8",
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source_manifest", type=Path)
    parser.add_argument("noise_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--snr-db", type=float, default=5.0)
    arguments = parser.parse_args()
    print(build(arguments.source_manifest, arguments.noise_dir, arguments.output_dir, arguments.snr_db))
