# Phase 4 — Voice Layer and ASR

## Status

Application implementation complete on 31 August 2026. Production acceptance remains conditional on durable consent/identity, deployed Redis/Kafka/object storage, field accessibility testing, and a hospital-recorded evaluation set. TTS is explicitly deferred at the product owner's request.

## Delivered scope

| Requirement | Implementation | Evidence |
|---|---|---|
| Device diagnostics | Permission check, selectable microphone, input-level test, and Hindi/English guidance | Patient kiosk lint and production build pass |
| Interactive ASR | Ordered PCM16 WebSocket stream with cumulative partial feedback and final result | WebSocket contract tests cover ready, partial, final, and completion messages |
| Hindi and English | AI4Bharat Hindi provider plus English-only Whisper language pack; unsupported languages fail to touch entry | Provider registry and unsupported-language tests |
| Noise handling | RMS, clipping, estimated SNR, speech presence, and a bounded acoustic-quality score | Silence and speech-burst unit tests |
| Confidence | Provider confidence remains nullable; no fabricated probability. Acoustic quality is reported separately | Contract and safety review |
| Graceful fallback | Every provider/connection/language failure returns the kiosk to touch entry without advancing the question | WebSocket and UI behavior tests |
| Review/correction | Final transcript enters an editable review step and advances only after patient confirmation | Kiosk production build |
| Temporary context | Turn state has a 30-minute default TTL in Redis when enabled, with deterministic memory mode for tests | Runtime adapter tests |
| Post-processing event | Metadata-only `ai.asr.completed.v1` event; hashes and references, never raw audio/transcript in Kafka | Contract tests verify transcript exclusion |
| Retention | No retention by default. Explicit separate consent plus AES-256-GCM encryption and S3-compatible storage are required | Fail-closed retention tests |
| Audit linkage | Tenant, session, encounter, consent, turn, hashes, provider, language and quality are linked in the audit event | Contract tests and runtime inspection |

Partial feedback is implemented by periodically transcribing the cumulative utterance. It improves perceived responsiveness but is not model-native token streaming. Moving to a streaming decoder is an optimization, not a protocol change.

## Measured model evidence

| Pack and condition | Samples | Mean WER | Cold load | Warm p95 | Mean warm RTF |
|---|---:|---:|---:|---:|---:|
| AI4Bharat Hindi, Kathbath noisy microphone | 10 | 5.52% | 45.55 s in the original process | 0.75 s | 0.85 |
| AI4Bharat Hindi mixed with real hospital ambient at 5 dB SNR | 10 | 14.21% | 28.51 s | 0.63 s | 0.054 |
| Whisper small.en, spontaneous Indian English (Monsoon), CPU | 10 | 6.36% | 23.78 s | 5.37 s | 0.552 |

The hospital-noise set is a controlled proxy: labeled noisy Hindi speech mixed with real hospital ambience. It is not a substitute for consented recordings from the pilot hospital. Small samples are useful as a regression smoke gate, not a clinical release claim.

Sources and licenses:

- Hindi: `SkunkWorkLabs/hindi-asr-benchmark`, Kathbath noisy subset.
- Ambient: `m42-health/hospital_ambient_noise`.
- Indian English: `VoiceArena/MonsoonASR-Open-ASR-leaderboard-en-IN`, CC BY 4.0.

Raw benchmark audio is intentionally excluded from Git. Manifests preserve dataset row provenance; aggregate and per-sample results are versioned.

## Runtime flow

1. Kiosk verifies microphone access and captures mono PCM16 at 16 kHz.
2. The browser opens `/ws/asr` with tenant, session, encounter, consent, language, and retention intent.
3. FastAPI validates context and language before resolving a model, preventing unauthenticated cold-load abuse through malformed requests.
4. Partial transcripts return synchronously over the socket. Redis holds only turn-level context when enabled.
5. Final text and independent signal-quality fields determine whether clarification is required.
6. The patient edits and confirms the transcript or switches to touch entry.
7. A metadata-only Kafka event supports post-processing/quality analysis. Optional audio retention encrypts before object upload and fails closed.

## Exit criteria

- [x] ASR/connection/language failures return immediately to touch entry without advancing progress.
- [x] Poor acoustic quality or a calibrated low provider confidence requests clarification.
- [x] Audio, transcript hash, consent, encounter, session and turn share auditable identifiers.
- [x] Hindi and Indian-English WER/latency are measured; a controlled hospital-noise Hindi result is recorded.
- [x] Patient can review and correct the final transcript.
- [ ] Durable server-issued voice context and consent validation in Postgres/Clerk.
- [ ] Redis, Kafka and encrypted object-store adapters exercised in a Compose integration test.
- [ ] Consented pilot-hospital noise corpus and clinician-approved medical-term thresholds.
- [ ] TTS/audio prompts (deferred by product decision).

The checked implementation criteria complete the Phase 4 code slice. The unchecked items are deployment and clinical-release gates and must remain visible in every release decision.

## Reproduction

```powershell
cd apps/api
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests tools
.\.venv\Scripts\python.exe -m mypy app tools

$env:ASR_PROVIDER='ai4bharat'
.\.venv\Scripts\python.exe -m tools.benchmark_asr benchmarks\english-indian-monsoon\manifest.jsonl --output benchmarks\english-indian-monsoon\results.json
```

On Windows, very deep OneDrive paths can exceed legacy path limits while installing Torch license files. Use Docker/WSL or a short virtual-environment path; the production Linux container layout is not affected.

## Authenticated voice transport (7 September 2026)

WebSocket `/ws/asr` still receives language, tenant/session/encounter/consent IDs
and retention preferences as query parameters. Those IDs alone do not authorize
speech. The first frame must be JSON `{"type":"authenticate","access_token":"..."}`
within ten seconds. Wait for `ready` before sending PCM16 audio. Credentials must
never be included in a URL. The kiosk obtains the token from its patient session.

The API verifies the patient role and tenant, then reads the consent under
PostgreSQL tenant RLS. Patient, encounter, treatment purpose, granted status and
expiry must match. Retention additionally requires the stored `audio_retention`
grant; client flags cannot grant permission. Checks repeat before partial/final
inference and after final inference before retention or result delivery. Denial
returns `voice_access_denied` with touch fallback. A database failure fails closed.

REST `POST /api/v1/asr/transcribe` requires Bearer authorization and multipart
`tenant_id`, `encounter_id`, `consent_id`, `language`, and `file`. It applies the
same patient/consent checks before inference and before returning the result.

This closes the stored-consent validation gap. The current identity adapter is
still local demo authentication, and the client session ID is correlation metadata;
server-issued durable voice sessions and external identity remain open gates.
