# ASR regression benchmarks

This directory versions manifests and results, not source audio. Audio is downloaded from the named public dataset and excluded by `.gitignore`.

| Directory | Speech source | Condition |
|---|---|---|
| `hindi-noisy` | `SkunkWorkLabs/hindi-asr-benchmark` / Kathbath noisy | Recorded noisy Hindi microphone speech |
| `hospital-noise-5db` | Same labeled speech plus `m42-health/hospital_ambient_noise` | Deterministic real-ambient mix at 5 dB SNR |
| `english-indian-monsoon` | `VoiceArena/MonsoonASR-Open-ASR-leaderboard-en-IN` | Spontaneous Indian-accent English, CC BY 4.0 |

Use `tools/fetch_fleurs_samples.py` to fetch a small Hugging Face viewer-backed labeled sample, `tools/mix_hospital_noise.py` to create controlled mixes, and `tools/benchmark_asr.py` to calculate normalized WER, latency and real-time factor.

These ten-sample sets catch regressions; they do not establish clinical fitness. Preserve source row IDs in manifests, do not commit patient or licensed source audio, and replace the proxy with a consented pilot-hospital evaluation before release.
