# Project completion review — 6 September 2026

Status: in progress. This is an evidence ledger, not a declaration of completion.
Scope: all runtime apps, APIs, service boundaries and plan gaps; ASR and OCR;
verified dead-code removal; showcase workflow. TTS and HiMed 8B are excluded.

## Verified in this review

- Baseline API suite: 376 passed, 25 skipped.
- After starting existing local infrastructure, integration-enabled API suite:
  396 passed, 5 skipped (126.38 seconds). Enabled PHASE7_INTEGRATION,
  PHASE8_INTEGRATION, PHASE9_INTEGRATION, PHASE9_KAFKA_INTEGRATION,
  PHASE9_POSTGRES_INTEGRATION and PATIENT_PORTAL_INTEGRATION.
- Real PP-OCRv5 mobile inference in the existing OCR container:
  `python -m tools.verify_real_ocr` passed, 3 regions, 5987 ms. This covers a
  clear synthetic English prescription, not handwriting or field accuracy.
- Speech-only startup regression tests: 2 passed. Both language providers warm
  without requiring OCR; requested warmup failure prevents startup.
- Ruff: `ruff check app tests tools` passed.
- Mypy: `mypy app tools` passed for 167 source files, with existing notes that
  untyped function bodies are not checked.
- Compose configuration validates. Existing data-service containers are running;
  PostgreSQL, MongoDB, Redis, MinIO, ClamAV and Elasticsearch report healthy.
  Previously restarting normalization/OCR/outbox/search workers recovered after
  their dependencies started.
- All three runtime frontends passed lint and production build: patient-kiosk,
  clinician-console and admin-console.
- Fresh offline Indian-English benchmark: 10 samples, mean WER 6.36%, warm p95
  54.693 seconds, warm mean real-time factor 5.507. Accuracy reproduces the
  stored baseline, but this run was concurrent with frontend builds and local
  infrastructure. Its latency is unacceptable for an interactive showcase;
  repeat under controlled load and investigate CPU scheduling before claiming
  real-time performance. Results: apps/api/benchmarks/english-indian-monsoon/review-results.json.
- ASR failure/startup regressions: 5 passed; Hindi preprocessing/startup tests:
  5 passed. Ruff passed again after the route changes.

## Changes

Continuation evidence:

- Repeated Indian-English benchmark with OMP_NUM_THREADS=4 and
  MKL_NUM_THREADS=4: unchanged 6.36% mean WER, warm p95 8.833 seconds,
  warm mean RTF 1.189. Different background load prevents attributing the
  whole improvement to thread limits. Compose now exposes ASR_CPU_THREADS.
- Real noisy-Hindi benchmark completed: 10 samples, mean WER 5.52%, warm p95
  0.592 seconds, mean warm RTF 0.080, cold load 10.013 seconds. The CLI now
  prints ASCII-safe JSON on Windows while preserving UTF-8 in its result file.
- Removed unbounded duplicate transcript/event storage when Redis/Kafka are
  enabled, capped local history at 128 entries, added lazy context expiry,
  removed the unused retained-audio mirror, and close the S3 client after upload.
  Storage and voice regressions: 14 passed. Full API suite at this checkpoint:
  385 passed, 25 skipped (integration switches off).
- English feature extraction no longer silently truncates at 30 seconds.
  Long recordings use native timestamp-driven decoding and the attention mask.
  Two regression tests pass. Real 45-second fixture decoding reaches the tail,
  but substitutes "repressed" for "refreshed"; this demonstrates why review is
  still required. The verifier separately reports tail WER and coverage using
  a 25% engineering smoke threshold, not a clinical accuracy threshold.

- Added an opt-in `asr` Docker build target that installs speech dependencies.
  Ordinary API and worker builds retain the lightweight `runtime` target.
- Connected provider selection, pinned Hindi revision, English model, model
  cache, voice Redis/Kafka adapters and speech warmup to Compose configuration.
- Added independent ASR warmup so the speech API does not try to initialize
  the separately deployed OCR runtime. Existing all-model warmup remains available.
- Documented real-ASR startup in SETUP.md and environment examples.
- Fixed WebSocket provider and initial context-store failures to return manual
  fallback, and emit ready only after context persistence succeeds. Non-object
  JSON control messages now return a recoverable protocol error.
- Removed an unreachable list conversion and overwritten tensor allocation
  in Hindi preprocessing; soundfile returns an array and conversion now happens
  once after optional resampling.

Rollback: select API_BUILD_TARGET=runtime, ASR_PROVIDER=mock and
ASR_WARMUP_ON_START=false, then rebuild the API. No database migration or data
deletion is involved. Model cache volumes can be retained.

## Still to establish

Patient-to-clinician handoff continuation:

- Replaced the hardcoded nurse dashboard and empty worklist with accepted
  PostgreSQL patient intakes, treatment-purpose confirmation, explicit review,
  context confirmation and draft generation. Doctor review receives the encounter
  through the navigation URL. Retry reopens the existing summary.
- New worklist reads enforce tenant/facility and current treatment consent;
  confirmation takes authoritative patient answers from PostgreSQL, requires
  explicit review and optimistic context versioning, and never auto-signs.
- API role/purpose/scope/concurrency tests and the live PostgreSQL integration
  journey pass: 3 tests. The latter now follows actual intake → staff projection
  → confirmed context → generation → signing → patient report, verifies tenant
  and facility denial, and verifies consent revocation removes intake visibility
  without deleting the already signed report.
- Ruff and focused mypy pass. Clinician frontend lint and production build passed
  after the handoff change. Full API regression suite: 389 passed, 25 skipped.
- Audit uses the existing memory emitter; central durable audit is still open.

7 September continuation:

- Live browser verification passed for synthetic clinical sign-in → worklist →
  accepted answers → explicit review → handoff generation → doctor review →
  submit → sign and lock. Verified that the patient API returned the same signed
  encounter afterward. Editing/signing controls were disabled after signing.
- Added `python -m tools.seed_showcase`, restricted to localhost, to produce one
  synthetic accepted intake via public APIs and output only walkthrough IDs.
- The shared clinician layout/sidebar contained a fabricated clinician identity,
  HPR verification, shift countdown and handoff count. Removed those claims.
- Fixed auth HTTP commands that reported revocation/rotation but kept the old
  token valid. Rotation preserves role, facility, tenant, MFA and session linkage;
  role changes are rejected. Demo tokens are random and expired entries are
  pruned. Bearer parsing is now explicit and case-insensitive. Twelve focused
  auth/session tests pass. This remains local demo identity, not Clerk/SSO.
- Full API tests after session fixes: 393 passed, 25 skipped; mypy passed for
  171 source files. Ruff passed. Visual review found evidence-label overlap and
  active-looking disabled controls; evidence now wraps in separate blocks and
  signed records display an immutable-state message instead of action controls.
  The UI change required removing redundant signed-state type comparisons;
  clinician lint passed and the subsequent build passed compilation/type checks.

- Fresh Hindi ASR checks are complete. Continue English latency evaluation and
  build the new speech image.
- Verify complete browser journeys (all three production builds now pass).
- Reconcile every plan against current implementation, particularly durable
  voice context/consent, Phase 6 alert ownership/escalation, staff handoff and
  administrative workflows. Existing documents contain conflicting status claims.
- Exercise the complete upload-to-OCR-to-reviewed-fact pipeline with real OCR,
  and patient intake through clinician signing and patient report retrieval.
- Remove dead code only after checking callers and runtime entry points.
- Complete operational, accessibility and showcase documentation checks.

Clinical validation, hospital-recorded evaluation data and external identity or
ABDM credentials cannot be inferred from local engineering tests.

Voice consent continuation:

- ASR WebSocket now authenticates the first frame before provider initialization;
  credentials stay out of URLs. REST requires Bearer authorization and scoped IDs.
- PostgreSQL/RLS checks bind consent to authenticated patient, tenant, encounter,
  treatment purpose, granted status and expiry. Retention requires the stored
  audio-retention grant. Revocation is rechecked before inference and saving output.
- Patient client waits for ready before sending buffered audio. Voice failures and
  navigation release the microphone, including cancellation during a pending
  browser permission request.
- Focused voice/API tests: 30 passed. Full API regression: 408 passed, 26 skipped.
  Live PostgreSQL patient/voice integration: 2 passed, including another-patient
  denial and consent revocation. Focused mypy and Ruff passed. Patient lint passed;
  production build is still being checked.
- This is not completion of the overall voice gate: external identity and durable
  server-issued voice session ownership still need implementation/verification.

Final checks for this voice change: patient production build passed (all routes),
patient lint passed, full API Ruff passed, and mypy passed for 172 source files.

## End-to-end OCR continuation — 7 September

Previous goal turn was progress (authenticated ASR and verified tests). This turn
verified the actual public API/Compose document pipeline and fixed three failures:

- Review API converted asyncpg JSONB geometry strings into character tuples,
  causing HTTP 500 for real OCR candidates. Decode JSONB before converting bbox
  and polygon arrays. Regression tests cover both raw JSON strings and decoded
  lists through public response serialization.
- Review decision SQL reused parameter $5 as text and varchar, causing a live
  PostgreSQL AmbiguousParameterError. Explicit varchar casts resolve inference.
- The narrow parser missed an unprefixed `METFORMIN 500 MG` line and interpreted
  `TAKE ONE TABLET DAILY` as medication DAILY. Instruction-only lines no longer
  become drug names. Name-plus-strength candidates without a form prefix carry
  explicit uncertainty and require source verification; no current-use assertion.

Added tools/verify_document_pipeline.py: local-only synthetic prescription through
patient authentication/consent, presigned quarantine upload, scan, normalization,
real OCR, extraction, explicit fixture review and asynchronous timeline promotion.
It requires exactly the expected drug and strength, verifies OCR provenance, checks
no pre-review timeline leakage, and asserts document-stated promoted facts. The
running OCR worker was independently checked: OCR_PROVIDER=paddleocr_fast.

Final live run passed: document f2f8c57f-a08b-4393-9ab1-a377b0fe2677, reviewed,
2 candidates and 2 reviewed facts. This proves the clear English printed fixture,
not handwriting, multilingual field accuracy or clinical acceptance.

Validation: 22 focused parser/geometry/evaluation tests; full API 411 passed,
26 skipped; live Phase 7 PostgreSQL/MinIO integrations 9 passed; Ruff passed;
focused mypy passed. Extraction worker rebuilt and restarted successfully.
All document dependencies, including the promotion worker, were restored locally.
API local demo/document/summary flags enabled for the synthetic walkthrough.
Updated stale document-processing-worker README and SETUP reproduction guidance.

Rollback: revert parser/repository changes and rebuild extraction worker/API.
No migration, source mutation or volume deletion was needed. Generated records
are synthetic and isolated in random tenants. Overall project review stays open.

## Alert lifecycle continuation — 8 September

Previous completed goal turn made progress: real OCR pipeline fixed and verified.
Plan audit confirmed Phase 6 persistence and lifecycle commands remain absent.
Added immutable alert transition contracts with explicit actor scope, ownership,
optimistic versions, acknowledgement versus resolution, verified handoff targets,
worker-only escalation and governed doctor disposition. Ten focused tests and
mypy pass. This is a foundation, not a deployed alert workflow. Durable storage,
API/input integration, verified workforce/governance adapters and UI remain open.
No migrations or runtime behavior changes were made in this slice.

## Durable alert storage continuation — 8 September

Added migration 0015 and PostgresAlertRepository. Verified atomic flag/history/
outbox writes, duplicate raises, concurrent acknowledgement, matching command
replay, changed-command rejection, tenant/facility isolation, forced RLS and
append-only history. Failure injection verifies rollback of projection and both
append-only records. Two live alert integration tests passed; isolated migration
apply/replay test passed. Full API: 421 passed, 28 skipped; Ruff/mypy passed.

Unexpected worktree change: the seven tracked app/summary_workflow files were
missing. Asked the user; user explicitly requested restoration. Restored those
seven files from HEAD and then ran the successful full regression suite.

Alert source/API integration, outbox transport, policy ownership and staff UI
remain open. Migration 0015 has only been exercised in isolated test schemas.
Previous goal turn was progress; this turn also changed authoritative code and
produced live database evidence. Overall scope and completion gates unchanged.

## Alert source/API/UI continuation — 8 September

Mounted authenticated durable alert APIs behind TRIAGE_WORKFLOW_ENABLED. Creation
loads accepted intake through the consent-scoped worklist; requests cannot supply
rule output or source text. Immutable intake fingerprint deduplicates repeat
checks. Staff listing requires treatment purpose; queue defaults to unresolved
states ordered by severity. Acknowledge and owning-doctor resolution use durable
versioned commands and protected rationale; unverified handoff/override/timer
commands are rejected at the public boundary.

Replaced Alerts stub with purpose confirmation, load/error/empty states, queue,
source paths, ownership and explicit acknowledgement/resolution. Added Worklist
entry point after explicit intake review and direct sign-in access. Configuration
examples, Compose and setup/contract documentation updated. Migration 0015 applied
to the local development DB (one migration). Local API flags enabled for testing.

Validation: 18 API/lifecycle tests passed; full API 429 passed, 28 skipped; Ruff
and mypy183 passed. Live repository tests passed and a new live API integration
proved stored consented intake -> idempotent raise -> acknowledge -> resolution
-> open queue exclusion -> historical visibility. Clinician production build and
lint passed before final sign-in-link wording edit; final rebuild running.
Rendered browser check verified treatment gate and missing-session message.
Full signed-in browser journey remains unverified. Patient emergency-state
persistence, outbox transport, timers and governed handoff/override remain open.
Final clinician lint and production rebuild passed after the sign-in-link and wording change.

## Alert outbox delivery continuation — 8 September

Added migration 0016, fenced alert outbox publisher and optional Compose triage
profile. Claims use SKIP LOCKED, bounded leases and five attempts by default;
leases use UUID fencing so expired/replayed attempts cannot mark a new attempt
successful. Only the earliest unpublished event per alert may be claimed.
Different alerts publish concurrently within the lease; a failed or dead-lettered
predecessor blocks later state events. Broker errors store a fixed safe error
class. Dead-letter replay preserves stable event identity and requires maintenance
DB access. Replay operations must currently be recorded in the operations log;
a governed replay API/central operator audit is not implemented.

Queue results and UI now distinguish pending, failed and broker-published event
status separately from clinician acknowledgement. Metadata allowlist rejects
unexpected event payload keys. Rule/source text and protected rationale are not
part of the transport payload.

Validation: five live PostgreSQL alert tests passed, covering retry, lease expiry,
stale completion rejection, event ordering, DLQ/replay and projected delivery
status; real PostgreSQL-to-Kafka integration separately passed, checking event ID,
alert key, tenant, event type and absence of symptom text. Publisher image built
and started; confirmed running without startup errors. Migration 0016 applied to
local DB. Full API regression and clinician rebuild still being collected.
Timed policy escalation, patient interruption-time persistence, consumer-side
notification workflow and verified staff handoff/override remain open.
Final delivery checks: full API 429 passed/32 skipped; Ruff passed; mypy184 passed; isolated migration apply/replay passed; clinician lint and production build passed.

## Patient safety persistence and touch intake — 9 September

Restored the seven tracked summary_workflow files with explicit user approval.
Added authenticated patient safety-confirmations endpoint: token-derived patient
and tenant, facility scope, matching active treatment consent, bounded confirmed
answers, canonical evaluation before any LLM dependency. Shared consent lock
serializes with revocation. All triggered flags, protected source evidence,
history and outbox intent commit together; identical versions deduplicate.
Patient callers cannot use clinician alert lifecycle commands or listing.

Assisted intake now persists warnings before the next-question request. Fixed
first-complaint emergency screen incorrectly requiring an existing AI question.
Browser verified synthetic sign-in -> consent -> assisted first complaint
"cannot breathe and heavy bleeding" -> focused urgent screen, saved warning
copy and no staff acknowledgement claim. API log had safety-confirmations 200
and no subsequent dialogue request. This was observed before the later touch
changes; touch browser verification remains pending.

Touch intake now checks each confirmed answer before advancing, blocks concurrent
submissions, pauses on warnings and stops on safety service failure. Human-readable
option labels replace opaque codes in safety inputs and submitted history; free
speech remains unchanged. Respiratory rule 1.0.1 and ruleset phase6.prototype.v2
add the existing English choice label "Breathing Difficulty". Prototype approval
status is unchanged. Added bilingual fixtures and answer-serialization tests.
Multi-select/scale controls reset between distinct questions.

Prior slice validation: API 429 passed/33 skipped, Ruff, mypy175 and patient lint/
build passed; six live PostgreSQL alert tests passed, one Kafka opt-in skipped.
New live authenticated patient test covers bad scope/consent/body, atomic two-flag
rollback, dedupe, protected-source preservation, metadata-only outbox and revoked
consent denial. Latest touch changes: two Node behavioral tests passed; full API
and patient lint/build running at this entry. Full project goal remains open,
including timer policy, governed handoff/override, consumer notification,
production identity, durable voice ownership and the remaining application audit.
Final touch validation: patient production build passed; targeted lint of all
changed patient sources/tests passed after converting the Node test to ES modules;
two Node behavioral tests passed. Full API run was 430 passed/33 skipped with one
stale ruleset-version assertion; corrected that assertion and all 16 focused
rule tests passed. Rules mypy passed. Browser then verified fresh synthetic
sign-in -> durable consent -> Allopathic -> Breathing Difficulty -> focused
urgent screen; no next question was shown and the saved/not-acknowledged wording
was visible. The full project review remains active.
Final API rerun: 431 passed, 33 opt-in skipped. Database inspection confirmed the
browser touch flag is open with RF-RESP-001 version 1.0.1 / ruleset v2, alongside
the earlier two assisted flags. Follow-up lifecycle review fixed acknowledgement
of a targeted handoff by someone other than the assigned recipient; all ten
lifecycle tests and rule/lifecycle Ruff checks passed. Public handoff remains
gated until verified workforce integration is implemented.

## Prototype facility escalation ladder — 9 September

Implemented app/rules/alert_timers.py and optional triage-timers Compose worker.
Explicit policy binds tenant/facility/worker, policy ID/version, owner reference
and up to five strictly increasing deadlines from original alert creation. Current
prototype steps escalate/re-escalate to doctor role and never lower or resolve.
No timers or thresholds are implicit clinical policy. The supplied 30/120-second
file is labeled synthetic demo only; runtime requires demo and triage flags.

Progress is stored as stable policy-fingerprint/step keys in append-only alert
history. Every transition also records a protected policy snapshot and outbox
intent. Due scans skip completed ladders and not-yet-due steps before limiting,
preventing starvation by those rows. Optimistic concurrency rejects staff-ack
races; repeated workers/restarts cannot duplicate the same policy step. Broker
availability is not needed for durable escalation. Exhausted ladders stay open
and escalated for staff response.

Validation: six policy tests; seven live PostgreSQL alert tests passed, one
opt-in Kafka test skipped. Tests cover restart, concurrent timers, step exhaustion,
facility scope and stale acknowledgement race. Ruff and mypy176 passed; full API
437 passed/34 skipped. Compose configuration validated; packaged image built;
two separate container runs each processed the next step for the three known
synthetic browser flags. No external notification was sent.

Governed activation remains incomplete: there is no central active-policy registry.
Stop all old-policy workers before replacing configuration; different policy
fingerprints are separate ladders and replacement uses original alert ages.
This gap, production clinical policy approval, consumer notification, verified
staff directory/handoff/override, production identity, durable voice ownership
and remaining whole-project audit are still open. TTS and HiMed remain excluded.

## Authoritative active-policy registry — 9 September

Migration 0017 adds immutable policy artifacts, one active fingerprint/revision
per tenant/facility and append-only activation history with operator attribution
and controlled reason. Reusing a policy ID/version with different contents fails.
Activation uses optimistic revisions plus transaction serialization. CLI changes
require maintenance DB access and operator/revision/reason arguments; normal
workers cannot self-activate. Production operator identity remains an external
integration boundary rather than a claim based on a supplied UUID.

Workers first check active policy and then recheck the exact fingerprint and
bound worker actor inside the alert-write transaction. A shared active-policy
lock is held through commit. Replacement/deactivation fences old workers and
waits for earlier writes, closing the previous concurrent-policy gap. Reactivation
of identical content resumes unfinished steps without repeating prior step IDs.
Existing non-timer command hashes retain compatibility for idempotent replay.

Validation: seven live PostgreSQL alert tests passed, one opt-in Kafka skipped,
including stale revision, version-content conflict, cross-tenant registry denial,
artifact immutability and deactivation between scan and command. Full API
437 passed/34 skipped; Ruff and mypy177 passed. Migration applied once and
replayed with zero changes. Docker image rebuilt; packaged status showed revision
0 and explicit synthetic activation returned revision 1. Deactivation check
running when this entry was written. Setup and worker documentation now describe
registry activation and fencing rather than manual old-worker exclusion.

Full-project goal remains open: production identity/clinical approvals, verified
staff handoff/override, notification workflow, durable voice ownership and the
remaining application/service/plan audit. TTS and HiMed remain excluded.
Packaged deactivation returned revision 2; the synthetic facility policy is paused. No alert/history/outbox rows were removed.

## Identity-provider verification foundation — 9 September

Audit confirmed auth/clerk.py is an in-memory registry, despite its token-validation
wording; production JWT validation was absent. Added a separate ClerkSessionVerifier
using pinned PyJWT[crypto] 2.13.0. It pins configured HTTPS issuer, RS256, audience
and authorized origins; requires session/time claims; rejects pending/impersonated
sessions; returns verified subject/session identity without external role/facility
claims. Public JWKS requests carry no patient token, do not follow redirects and
are bounded to 64 KiB/10 keys. Cache lifetime is 60 seconds; forced unknown-key
refreshes are limited to one per five seconds. Expired cache plus provider failure
fails closed, without silently using stale keys.

Sources checked: https://clerk.com/docs/guides/sessions/manual-jwt-verification
and https://pyjwt.readthedocs.io/en/stable/api.html . Pinned library installed in
project venv and both dependency manifests updated. First 18 security tests passed,
Ruff and mypy passed; required-claim cases added and running. The module is NOT YET
wired into authentication: durable internal subject mapping, role/facility grants,
revocation, provider switching and frontend Clerk sessions remain next work.
Existing demo behavior is retained until that complete boundary can be verified.
Final verifier checks: 26 security tests passed; Ruff passed. Required-claim fixtures now omit claims before signing, including issuer; no test relies on the JWT encoder accepting an invalid issuer value.

## Internal identity mapping and shared authentication — 9 September

Restored and verified all seven tracked summary_workflow files; no diff remains
in that directory. Added migration 0018 for durable external-subject/internal-UUID
bindings, versioned append-only grant history and platform session revocation.
Forced RLS scopes lookup to the verified issuer/audience/subject. Maintenance
provisioning requires explicit grants, operator attribution, controlled reasons
and optimistic versions; changing an existing internal identity or tenant is
rejected. External tenant/role/facility claims never become internal authority.

HTTP and ASR authorization now share provider selection. Demo credentials are
accepted only in development/test; Clerk mode has no demo fallback. Each verified
session requires an active internal grant and application-allowed role. Added
private/no-store current-identity and platform-session revocation endpoints.
Revocation persists across refreshed JWTs with the same external session ID.
Provider sign-out remains a separate frontend responsibility.

Validation: real RSA signatures with synthetic JWKS transport plus PostgreSQL
restricted-role integration verified forged claims, missing/inactive grants,
wrong audience, immutable history, stale provisioning, relinking rejection and
durable revocation. Targeted API/identity run: 11 passed. Full API: 465 passed,
35 opt-in skipped; Ruff passed; mypy passed across 181 files. Migration applied
once to local database, replay applied zero. Shared integration fixture moved
into conftest; triage integration regression is being checked separately.

Added environment/Compose configuration and docs/contracts/IDENTITY-API.md with
provisioning, endpoint, rollback and validation limits. Real Clerk configuration,
frontend login, verified workforce grants and the remaining full-project review
remain open. Supplied maintenance operator UUIDs are attribution, not proof of
workforce authority. No production identity provider was configured or claimed
verified. TTS and HiMed remain excluded.

Final checkpoint: seven live triage PostgreSQL tests passed (Kafka opt-in skipped); shared identity/voice checks 17 passed and Ruff passed after provider timeout handling. Summary workflow restoration verified against Git with no remaining diff.

## Clinician Clerk integration — 9 September

Added official @clerk/nextjs 7.9.1 (exact version and lockfile). ClinicalIdentity
provides provider sign-in, internal /auth/me grant verification before mounting
clinical screens, explicit access-denied/retry states, and platform revocation
followed by provider sign-out. Summary, document review and search requests now
obtain current credentials through a shared adapter. Clerk mode never reads demo
tokens from sessionStorage; internal clinical display role comes from the API.
Local demo sign-in remains separately configured.

Next.js proxy pins configured audience and origins and protects clinical routes.
Inspected installed SDK: its audience verifier allows absent aud, so the proxy
adds a mandatory exact single-audience check. Missing keys/configuration returns
private/no-store 503. Added public build arguments and runtime-only secret wiring
to Docker/Compose, environment examples, and the identity contract.

Validation: seven behavioral credential/proxy tests passed (SDK authentication
itself is stubbed in the proxy tests); ESLint passed; full Next.js production
build and TypeScript passed. Browser inspection of the built local login on 3011
confirmed the labeled synthetic form renders. Running actual Next.js in Clerk
mode without keys on 3012 returned 503 with private/no-store, not a demo fallback.
These checks do not verify a real provider sign-in, refresh, SSO or MFA session.
No Clerk application/account or real credentials were created. Patient and admin
frontend identity integration and remaining service/pipeline audit remain open.

## Patient identity isolation and recording preparation — continuation

Continued from the existing checkpoint. Added patientIdentity adapter for verified
internal patient/facility metadata and per-request SDK token retrieval, with no
Clerk credential persistence. Patient HTTP requests and ASR initial authentication
now use it. Binding a different patient clears prior encounter/consent/retention
references; old screens and delayed token refreshes cannot use a new patient's
token. A delayed 401 only clears the session that issued that request. Existing
demo behavior remains the default. Official Clerk SDK 7.9.1 installed and pinned
in the patient app; patient Clerk UI is NOT yet wired, and Clerk mode should not
be enabled there until that and durable kiosk-session creation are completed.

Eight behavioral tests passed, including stale-screen requests, account switches
during refresh, delayed unauthorized responses, role/facility denial and existing
questionnaire semantics. Full patient lint and production build/TypeScript passed;
targeted lint after the final delayed-response fix was started separately.

User expanded the deliverable to a Recordly workflow/dashboard recording. Found
the installed executable at C:\Program Files\Recordly\Recordly.exe, with updater
metadata identifying webadderall/Recordly. No recording has been made yet. Added
review/RECORDLY-WALKTHROUGH.md to track feature coverage, synthetic-data scope and
required export verification. Recorder control/export remains to be tested after
the remaining workflows are complete. Added the temporary npm cache to gitignore.

Patient identity checkpoint: targeted lint after the delayed-response fix passed. All eight behavioral tests passed; no Recordly capture has started. Next work is patient login UI plus durable authenticated kiosk/voice-session ownership, followed by remaining dashboard/service coverage.

## Durable authenticated patient intake sessions — continuation

Added migration 0019 and patient session repository/API. Creation derives patient
and tenant from authentication, checks facility scope, generates session and
encounter UUIDs server-side and supports stable idempotent retry. Sessions belong
to one provider/application/login session, expire after five minutes idle and
thirty minutes total, and cannot be touched after expiry or ending. Creation/end
history is atomic and immutable; both tables force tenant/patient RLS. Touch/end
deny wrong patient, tenant, facility and login without exposing ownership details.

Patient start now calls this authenticated endpoint with a current credential,
retaining the returned server IDs. It no longer uses the unauthenticated demo
kiosk endpoint or invents encounter IDs in the browser. Existing anonymous demo
session APIs remain demo-gated while their callers/retirement are audited.

Validation: local PostgreSQL was confirmed stopped and restarted without volume
deletion. Five targeted tests passed, including live restricted-role RLS,
ownership, restart/retry, expiry, end, immutable history, API role/facility denial
and refresh-stable owner keys. Ruff and new-module mypy passed. Full API baseline
465 passed/36 skipped before the four new API unit cases were added; those cases
passed in the targeted run. Patient behavioral tests now nine passed; changed
frontend lint and TypeScript passed. Migration applied once, replay applied zero.

Remaining: enforce session ownership in ASR and downstream intake actions,
implement activity/end handling, connect patient Clerk UI and complete the rest
of the dashboard/service/plan audit and Recordly capture. These are unfinished;
the new table/API alone is not proof of full voice-session enforcement.


## 10 September — ASR session enforcement and remaining-work inventory

Recording was cancelled by the user. ASR now requires a durable active session
owned by the authenticated patient/login/facility and matching the encounter.
REST requires session_id; WebSocket and REST recheck before releasing results,
including partial transcripts. Updated consent integration and smoke fixtures.
Latest default API run: 472 passed, 37 skipped. Live PostgreSQL session/consent
checks passed; two voice tests additionally prove wrong-login/encounter denial,
ended-session denial and idle-expiry denial. No real-browser rerun for this change
yet. Patient activity/end UI and downstream intake enforcement remain open.

The current consolidated backlog is [FINAL-REVIEW-REMAINING.md](FINAL-REVIEW-REMAINING.md),
created at the user's request. It distinguishes implementation gaps, verification,
plan reconciliation and external gates. Historical pending statements above may
be superseded by later evidence; they are not completion claims.
