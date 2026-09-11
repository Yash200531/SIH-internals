# Pre-Phase 9 — Patient dashboard, reports, OCR intake and speech loop

**Status:** Implemented and locally verified engineering candidate

**Provider policy:** `mock` clinical generation and `mock` TTS only. This slice
must not download or call HiMed-8B, vLLM, OpenAI, Claude, Bhashini, or another
generative/speech model or hosted inference API. The separate document worker
uses downloadable official PP-OCRv5 OCR weights; this is the intentional real
model exception, requires no API key, and never receives clinical text remotely.

**Primary user:** patient or caregiver using the MediKiosk patient web surface

## 1. Objective

Finish the patient-facing engineering path before Phase 9 so a patient can:

1. start a safe Hindi/English kiosk flow;
2. answer adaptive SOCRATES questions by voice or touch, confirm the transcript,
   hear the next prompt from deterministic mock TTS, and review/reject the draft;
3. upload a prescription into the existing consent-scoped Phase 7 pipeline,
   whose dedicated worker runs the real CPU PP-OCRv5 mobile detector and recognizer;
4. see the real processing state without seeing unreviewed OCR as clinical truth;
5. view and download complete clinician-signed reports and reviewed document
   timeline entries that belong to the authenticated patient; and
6. understand empty, loading, failure, offline and urgent-help states.

The engineering outcome is a working local/synthetic-data candidate. It is not
clinical validation, production identity approval, accessibility certification,
or a compliance claim.

## 2. Repository audit and revised gap ledger

| Capability | Evidence at start | Required change |
| --- | --- | --- |
| Patient landing screen | Branded but voice orb only toggles local state | Make navigation/status truthful and route to working patient tasks. |
| Kiosk session | UI contains a TODO and skips the API | Create and persist a real constrained kiosk session. |
| Consent | UI creates a random browser ID and contains a TODO | Persist consent through the API in demo mode and fail visibly when unavailable. |
| Adaptive questions | Mock clinical dialogue is connected | Preserve it, make session context shared, and retain accessible urgent/manual fallback. |
| Voice answers | WebSocket ASR plus correction/confirmation exists | Verify the confirmed transcript alone advances the dialogue. |
| Spoken prompts | Browser `speechSynthesis` is used | Replace it with a deterministic server-side mock TTS provider and playable WAV output. |
| Summary review | Editable/rejectable browser draft exists | Persist an explicit patient decision/outcome and route completion to dashboard/records. |
| Patient records | `/records` is an 11-line placeholder | Add authenticated self-scoped dashboard, report list/detail/download and real UI states. |
| Prescription upload | Secure staff Phase 7 path and real PP-OCRv5 adapter exist | Add patient-self endpoints and UI that reuse the registry, object store and worker chain; make the real worker dependency/runtime explicit. |
| OCR truth boundary | Reviewed facts/timeline exist for clinicians | Expose only patient-owned status plus promoted/reviewed results; never raw OCR text. |
| Production dashboard scaffold | `frontend/apps/patient-dashboard` contains README placeholders only | Keep one deployable patient surface in `apps/patient-kiosk`; document the scaffold as non-runtime. |

## 3. Safety, privacy and accessibility invariants

1. Kiosk pre-auth routes never search for or display longitudinal PHI.
2. Patient portal routes use `/me`; patient identity is derived from a validated
   token and never accepted as an arbitrary path/query parameter.
3. `role=patient`, a UUID `user_id`, tenant scope and facility scope are required.
4. Cross-patient, cross-tenant and cross-facility objects return not-found/denied
   without leaking whether another patient's record exists.
5. Only `signed` Phase 8 summaries are patient-visible. Draft, rejected and
   in-review content remains clinician-only.
6. OCR text and extraction candidates are never patient-visible as verified
   facts. Only processing status and Phase 7 clinician-promoted facts/timeline
   may appear.
7. Uploads preserve Phase 7 consent authorization, MIME/size verification,
   quarantine, immutable source, scanning, normalization, OCR, extraction,
   review and promotion boundaries.
8. Mock TTS is deterministic, offline, bounded and clearly identified as mock.
   Unsupported provider configuration fails closed.
9. Emergency messaging interrupts routine questioning, receives focus and has
   an assertive live region plus a manual staff-help action.
10. Every async screen exposes loading, empty, success and recoverable error
    states without color-only meaning; touch targets remain at least 44px.
11. Audit and event metadata contain identifiers/status only, never report text,
    transcripts, OCR text or synthesized prompt content.
12. Local demo identity is development-only and documented for synthetic data;
    production authentication remains the Clerk/hospital-SSO approval boundary.

## 4. API and service contract

### Patient self-service

Authenticated prefix: `/api/v1/patient-portal/me`

- `GET /dashboard` — counts, recent signed reports, recent document states.
- `GET /reports` — patient-owned signed summaries only.
- `GET /reports/{report_id}` — full clinician-approved signed content and evidence metadata.
- `GET /reports/{report_id}/download` — UTF-8 text download with integrity/version metadata.
- `GET /timeline` — reviewed document timeline for the authenticated patient.
- `GET /documents` and `GET /documents/{document_id}` — patient-owned upload states.
- `POST /documents` — register a patient-owned prescription upload.
- `POST /documents/{document_id}/upload-session` — exact-object short-lived grant.
- `POST /documents/{document_id}/finalize` — verify and commit uploaded bytes.
- `POST /documents/{document_id}/cancel` — cancel an unfinalized upload.

All repository queries are tenant-scoped. PostgreSQL runtime paths set the RLS
tenant context before reading. In-memory repositories remain test doubles only.

### Mock speech output

- `POST /api/v1/tts/synthesize`
- input: bounded Hindi/English text, language and optional voice identifier;
- output: `audio/wav`, deterministic mono PCM, provider/version headers;
- provider: `mock` only; any other setting returns service unavailable.

The browser speech loop is ASR WebSocket → editable transcript confirmation →
mock dialogue/SOCRATES → mock TTS WAV playback. Typed answers use the same
dialogue and TTS path after confirmation/submit.

## 5. Data and ownership design

- Extend the existing Phase 8 repository with patient-scoped signed-summary
  reads; do not create a second summary store.
- Extend the Phase 7 registry repository with patient-scoped list/read methods;
  do not duplicate upload or OCR state machines.
- Patient report DTOs are a read-only projection. They do not mutate clinician
  summaries or claim that evidence links are patient-readable source files.
- Downloads are generated from the signed structured record at request time and
  include signature hash, version and sign-off timestamp.
- The dedicated worker adds pinned PaddlePaddle/PaddleOCR dependencies and
  official PP-OCRv5 mobile weights. It adds no credential or hosted inference
  dependency; clinical dialogue and TTS remain deterministic mocks.

## 6. Dependency-ordered implementation plan

### P0 — Contract and guardrails

- Publish this spec/gap ledger and a decision record for self-scoped reads and
  deterministic mock TTS.
- Add configuration that defaults TTS to `mock` and fails closed otherwise.

Acceptance: scope, non-goals, authorization and verification commands are
reviewable before application code changes.

### P1 — Mock TTS vertical slice

- Add TTS contracts, deterministic WAV provider, registry and route.
- Unit/API test RIFF validity, determinism, input bounds, languages, safe headers
  and non-mock failure.
- Connect `AudioPrompt` to the API and remove browser speech synthesis.

Acceptance: a Hindi or English prompt produces playable local WAV bytes with no
network/model/API-key dependency.

### P2 — Patient self-scoped reports vertical slice

- Add signed-summary patient repository queries and patient portal service/router.
- Implement dashboard, list, detail, download and reviewed timeline projections.
- Test role, identity, tenant, facility, status and cross-patient boundaries.
- Replace `/records` with accessible bilingual API-backed states.

Acceptance: a patient token can view/download only that patient's signed report;
draft/rejected/other-patient records are inaccessible.

### P3 — Patient prescription-to-OCR vertical slice

- Add patient-owned registry list/read and self-scoped upload commands that call
  the existing Phase 7 repository, authorizer and object-store boundaries.
- Add an accessible upload/status UI with exact accepted types and limits.
- Test register → grant → upload → finalize and authorization failures; run the
  existing worker integration chain through promoted reviewed output.

Acceptance: a real synthetic PDF/image enters quarantine and progresses through
the Phase 7 pipeline; the patient UI shows status but never raw/unreviewed OCR.

### P4 — Kiosk and speech-loop completion

- Replace browser-random workflow IDs where API/session values exist.
- Connect kiosk session and consent; preserve manual fallback.
- Make assisted questions play mock TTS, accept confirmed voice answers, expose
  assistant/emergency status and persist the patient accept/reject outcome.
- Remove misleading simulated waits/TODO completion behavior.

Acceptance: one bilingual synthetic case completes speak → confirm → adaptive
question → spoken prompt → editable/rejectable draft with no external provider.

### P5 — Verification, documentation and evidence

- Backend format/lint/type checks and focused/full tests.
- Live PostgreSQL/MinIO/worker integration tests for reports and OCR.
- Patient frontend lint and production build.
- Browser smoke for reports, download, upload state and assisted voice fallback;
  keyboard, focus, live-region and responsive checks.
- `docker compose config`, generative/speech mock-only configuration audit,
  real-OCR execution check and `git diff --check`.
- Update README, SETUP, architecture/safety docs, roadmap, implementation ledger,
  `whatsdone.md` and `todo.json` with measured evidence and remaining approvals.

Acceptance: every claimed capability is tied to a passing command or captured
manual verification; external clinical/accessibility/security approvals remain
explicitly pending.

## 7. Test commands

Commands may be refined to match repository scripts, but the final ledger must
record the exact commands and results:

```powershell
cd apps/api
python -m ruff check app tests
python -m mypy app
python -m pytest -q

cd ../../apps/patient-kiosk
npm run lint
npm run build

cd ../..
docker compose config
git diff --check
```

Focused tests must cover mock TTS, patient portal API/service, patient upload,
signed-report filtering, download integrity, cross-scope denial and S2S wiring.

## 8. Non-goals and open release gates

- No autonomous diagnosis, prescribing, clinical advice or AI sign-off.
- No real TTS/LLM provider and no speech/generative-model download. Real
  PP-OCRv5 remains part of the separate document-processing boundary.
- No claim that deterministic mock tones are intelligible production speech.
- No production patient identity launch until Clerk/SSO, account linking,
  recovery, residency and revocation controls are approved.
- No patient exposure of unsigned notes or unreviewed extraction.
- No clinical, legal, DPDP, HIPAA, ABDM or accessibility certification claim.
- Formal clinical-safety, privacy/security, assistive-technology, operations and
  facility-owner approvals remain required before deployment.

## 9. Definition of done

This pre-Phase 9 slice is done only when P1–P5 are implemented, tested and
verified; the patient UI has no placeholder record/consent/session paths; the
generative/speech mock-only audit finds no runtime dependency on HiMed-8B, vLLM, OpenAI or API
keys; and documentation distinguishes engineering evidence from pending
external approval.

## 10. Verification record — 2026-09-05

- Ruff: passed for `app`, `tests` and `tools`.
- mypy: no issues in 146 application source files.
- backend: 307 passed, 22 intentionally gated provider/integration tests skipped.
- patient frontend: ESLint passed; Next.js 16.3.3 production build passed with
  nine product routes.
- patient persistence: one live self-scope/consent/intake/report integration
  test passed in an isolated PostgreSQL schema.
- document pipeline: live scan → normalize → OCR service → review/promotion
  integration passed against PostgreSQL, MinIO, MongoDB and ClamAV.
- real OCR: the dedicated Docker image downloaded the official
  `PP-OCRv5_mobile_det` and `PP-OCRv5_mobile_rec` artifacts and recognized
  `METFORMIN 500` from a generated prescription image (`3` regions,
  `PASS provider=paddleocr_fast model=PP-OCRv5-mobile`).

The OCR check proves executable model wiring and clear printed-text recognition;
it does not replace the pending representative prescription, handwriting,
camera-capture, script and clinical-quality evaluation.
