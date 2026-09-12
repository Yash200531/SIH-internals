# Final review — remaining work

Updated: 10 September 2026. Status: **in progress; project completion is not established**.
Project: `C:\Users\shiva\OneDrive\Documents\NotMID\patient-case-taking-platform`.

This is the remaining-work checklist for the existing review, not a restart. It combines current source checks, the review evidence ledger and the project plans. An unchecked verification item does **not** mean the feature is absent; it means the final review still needs sufficient evidence. Further review can uncover additional defects.

**Excluded by the user:** TTS and HiMed 8B. **Cancelled by the user:** Recordly/video recording. Neither is a completion requirement for this review.

Labels: **Implement** = known unfinished integration/feature; **Verify** = inspect and exercise current implementation; **Reconcile** = resolve conflicting plans, claims or scope; **External** = evidence/credentials/approval that local synthetic tests cannot supply. Close an item only with a source/test/runtime evidence link and result.

## Current checkpoint — do not redo from scratch

- The seven tracked summary-workflow files were restored as authorized.
- Earlier evidence covers real Hindi/English ASR, a clear printed English prescription through real OCR and promotion, and a synthetic intake-to-clinician-signature journey. These are bounded examples, not whole-project proof.
- Durable identity bindings, patient intake sessions, alert lifecycle/outbox/timers and clinical search have implementation and targeted evidence; remaining integration and release checks are listed below.
- Latest API regression: **472 passed, 37 skipped**. Skipped integration/evaluation tests are not passes.
- Latest live PostgreSQL checks: voice consent and patient-session lifecycle passed; additional voice checks passed for wrong login/encounter, ended sessions and idle expiry.
- ASR now checks the server-issued session against patient/login/facility/encounter before processing and before returning transcripts, including partial transcripts. Full current-browser verification remains open.

## 1. Plan reconciliation and whole-project coverage

- [ ] **Reconcile** every requirement and exit gate in BUILD-ROADMAP and the Phase 4, 5, 6, 7, 8, pre-Phase-9 and Phase-9 plans against current code and evidence. Older unchecked items and historical “not implemented” statements are not authoritative status.
- [ ] **Verify** every runtime application, route, worker, package and logical service has an owner and a disposition: implemented/tested, unfinished, intentionally deferred or excluded.
- [ ] **Reconcile** conceptual names in CONTEXT-GRAPH/services documentation with actual patient-kiosk, clinician-console, admin-console and FastAPI runtime boundaries.
- [ ] **Reconcile** README, SETUP, architecture diagrams, phase status, `whatsdone.md` and `todo.json`; remove unsupported completeness, performance, ABDM and clinical-validation claims.
- [ ] **Verify** all public API routes and feature-flag combinations, including demo disabled, have a working authorized path and explicit unavailable behavior.
- [ ] **Reconcile** later hospital-pilot and scale roadmap work separately from the local showcase. Do not silently treat roadmap aspirations as implemented or expand into model work excluded by the user/current mock-only ADR.

## 2. Identity, registration and shared-device sessions

- [ ] **Implement** patient Clerk provider/sign-in UI, protected routing and platform-session revocation on logout using the existing identity adapter.
- [ ] **Implement** patient facility selection where multiple grants exist; prevent accidental cross-facility continuation.
- [ ] **Implement** administration authentication and authorization appropriate to actual operational actions.
- [ ] **Implement** durable patient-session enforcement in downstream intake/dialogue/safety actions where session context is required; reject invented, expired, ended and other-login sessions.
- [ ] **Implement** activity-based session touch, idle/hard-expiry UX and server-side end handling. Clear consent/intake/voice state and release the microphone on expiry/logout/navigation.
- [ ] **Verify** delayed responses, token refresh, multiple tabs, back navigation and patient switching cannot display or submit the previous patient's data.
- [ ] **Verify** clinician Clerk login/logout, current-token requests, grant changes and revocation across a real running application.
- [ ] **External** configure real Clerk application credentials and exercise issuer/audience/client boundaries, login, refresh, MFA and provider outage; stubbed SDK/JWT tests alone do not establish this.
- [ ] **Verify** identity lifecycle/webhook signature validation, replay handling, account linking, staff facility membership and revocation; implement missing in-scope paths.
- [ ] **Reconcile** assisted registration, receptionist/caregiver roles, delegation, patient duplicate resolution and merge/unmerge requirements with implemented workflows.
- [ ] **Verify** anonymous/demo endpoints cannot access records in non-demo operation, and patient/staff identifiers never come from untrusted body fields when verified identity should supply them.

## 3. Patient dashboard and intake

- [ ] **Verify** every patient route/button: entry, Hindi/English selection, consent, touch intake, voice intake, confirmation, submission, records, report detail/download and document timeline.
- [ ] **Verify** consent creation/list/revocation, category-specific permissions and expiry throughout active workflows.
- [ ] **Verify** corrected transcripts and confirmed answers survive navigation/retry without becoming unreviewed clinical facts.
- [ ] **Verify** accepted/rejected submissions, duplicate requests, interrupted network requests and retry recovery are consistent with durable state.
- [ ] **Verify** emergency interruption is immediate, understandable in both languages and connected to staff workflow without claiming staff receipt prematurely.
- [ ] **Verify** loading, empty, denied, offline, expired-session and service-failure states give a working next action.
- [ ] **Reconcile** offline capture/sync and caregiver/assisted modes: inspect existing support, implement in-scope gaps or document explicit roadmap deferral.
- [ ] **Verify** patient reports contain only signed summaries and reviewed document facts; drafts/raw OCR cannot leak through APIs, downloads or browser caches.

## 4. Nurse and doctor dashboards

- [ ] **Verify** all worklist navigation, filters, paging, refresh and detail states against real accepted intakes and active consent.
- [ ] **Verify** nurse/doctor role distinctions and treatment-purpose/facility restrictions across UI and direct API calls.
- [ ] **Verify** intake review → context confirmation → draft generation → evidence inspection/edit → review submission → signature → patient retrieval on the latest code.
- [ ] **Verify** concurrent edits, stale versions, generation retries and signed-record immutability through browser and API behavior.
- [ ] **Verify** document review, source preview, correction, rejection, unreadable/rescan/defer/manual-entry actions and promotion from the clinician UI.
- [ ] **Implement** remaining governed staff handoff/override flows; public commands currently remain restricted where workforce/policy prerequisites are missing.
- [ ] **Verify** alert ownership, acknowledgment, resolution, history and escalation states are accurately shown and actionable.
- [ ] **Verify** every enabled control works; remove misleading fabricated identities/counters or replace them with authoritative data.

## 5. Administration and operations dashboard

- [ ] **Implement** real admin overview: current source still renders three static zero counters for Active Users, Facilities and Active Sessions.
- [ ] **Reconcile** the required admin feature set against operations/privacy plans and the existing navigation before adding controls.
- [ ] **Implement** authorized APIs/UI for the agreed facility, user/session and operational views; expose only necessary aggregate/operational data.
- [ ] **Verify** operational visibility for worker failures, pending/dead-letter work, queue age and workflow status.
- [ ] **Verify** any retry, replay, kill-switch or policy controls have authorization, concurrency handling and durable audit.
- [ ] **Verify** admin isolation from clinical content, empty/loading/error states, keyboard access and real data refresh.

## 6. ASR and voice pipeline

- [ ] **Verify** the complete current browser microphone → authenticated WebSocket → real Hindi/English inference → correction/confirmation → intake handoff path.
- [ ] **Verify** the REST upload fallback supplies the new required server-issued `session_id`; update remaining examples, tools and external callers.
- [ ] **Verify** microphone denial/cancellation, disconnection, slow inference, silence/noise, unsupported audio/language, malformed control frames and size limits.
- [ ] **Verify** session/consent revocation during inference and retention, plus no transcript release after authorization fails; latest backend regressions cover key cases, browser/runtime checks remain.
- [ ] **Verify** retained audio requires the durable retention grant and encrypted restricted object storage; consent withdrawal/retention cleanup follows the documented policy.
- [ ] **Reconcile** planned Redis/Kafka voice adapters with the revised bounded local context design; preserve required durable metadata without reintroducing duplicate PHI storage.
- [ ] **Verify** the ASR Docker image, cold/warm startup, model cache/revisions, CPU limits and manual fallback on a reproducible local startup.
- [ ] **Verify** English interactive latency under controlled representative load; report measured hardware/latency rather than claiming real-time performance.
- [ ] **Verify** longer audio, Hindi/English code switching, medical terms and noisy input beyond the small existing fixtures.
- [ ] **External** obtain representative consented recordings and clinician-approved error thresholds for clinical accuracy claims.

## 7. OCR and document pipeline

- [ ] **Verify** fresh full pipeline: upload → quarantine → malware scan → normalization → real OCR → extraction → clinician review → promotion → patient timeline/search.
- [ ] **Verify** PDF and image formats, multiple pages, rotation, blur, low contrast, oversized/corrupt files, duplicate uploads and incomplete uploads.
- [ ] **Verify** Hindi/mixed-language documents, camera captures and handwriting against declared support; a clear printed English fixture does not establish these capabilities.
- [ ] **Verify** medication, strength, unit, date, negation and uncertain-field extraction with source geometry and explicit review; missing values must not be fabricated.
- [ ] **Verify** worker crash/restart, duplicate delivery, stale leases, bounded retries, dead-letter handling and replay across every document stage.
- [ ] **Verify** failed scanning/quarantine cannot be bypassed; previews expire and recheck patient/tenant/facility/consent scope.
- [ ] **Verify** retention, abandoned-upload cleanup, immutable source/provenance, kill switches and manual fallback in actual storage.
- [ ] **External** complete representative OCR/field-accuracy evaluation and the pending Phase-7 owner/accessibility/rollout approvals before making clinical release claims.

## 8. Dialogue, summary and clinical provenance

- [ ] **Verify** structured dialogue rules, bounded question progression, missing/contradictory answers, emergency interruption and manual fallback.
- [ ] **Verify** mock-only provider policy and schema validation on all clinical generation paths; TTS and HiMed remain excluded.
- [ ] **Verify** source evidence survives transcript correction, document review, summary regeneration and clinician edits.
- [ ] **Verify** patient-stated, document-stated and clinician-confirmed facts remain distinct; historical medication does not silently become current use.
- [ ] **Verify** patient-friendly text, uncertainty and report downloads reflect the signed authoritative note without invented diagnosis/prescription.
- [ ] **Verify** summary outbox publication/recovery and source retrieval under storage/provider failures.
- [ ] **Reconcile** remaining Phase-5/8 evidence and safety gate claims against the newer durable workflow implementation.

## 9. Alerts, escalation and notification delivery

- [ ] **Implement** remaining notification consumer/in-app staff delivery and durable receipt/status handling; Kafka publication is not staff receipt.
- [ ] **Implement** governed staff assignment/handoff/override prerequisites and the applicable UI/API paths.
- [ ] **Verify** policy activation/deactivation, immutable revision history, facility scoping and timer behavior across restarts and concurrent commands.
- [ ] **Verify** end-to-end confirmed symptom → one durable alert → staff queue → acknowledgment → escalation/resolution with complete history.
- [ ] **Verify** duplicate/out-of-order events, expired worker leases, retries/dead letters and poison-message recovery without duplicate escalation.
- [ ] **Verify** timer/outbox health and actionable delivery/queue-age metrics.
- [ ] **Reconcile** SMS/WhatsApp and paging requirements with adapters and explicit opt-in policy; do not send external messages during synthetic testing.
- [ ] **External** establish clinical owners, approved thresholds/escalation recipients and representative clinical validation. Prototype policies do not establish these approvals.

## 10. Search, longitudinal context and FHIR

- [ ] **Verify** clinician search, language/query handling, filters, paging, source links and timelines through the latest browser build.
- [ ] **Verify** doctor/patient CSV exports, formula-injection defenses, row limits and nurse denial.
- [ ] **Verify** only signed summaries/reviewed facts enter the index and every result remains subject to authoritative access checks.
- [ ] **Verify** synchronization after signing/promotion, duplicate/out-of-order events, consent/access changes and stale/deleted projections.
- [ ] **Verify** real Elasticsearch/Kafka/PostgreSQL outage recovery, scoped reconciliation, full rebuild, alias switching and rollback using the runbook.
- [ ] **Verify** FHIR R4 retrieval/mappings and patient self-scope against published contracts.
- [ ] **Verify** durable search audit and fail-closed behavior when required audit persistence fails.
- [ ] **External** representative Hindi/English relevance, projected-load evidence, recovery/cost review and production approvals remain distinct from the small synthetic benchmark.

## 11. Services, infrastructure and operational recovery

Each entry needs current startup/readiness, normal operation, failure/retry, restart and shutdown evidence; prior healthy containers do not prove current readiness.

- [ ] **Verify** PostgreSQL and migrations, including clean install, replay and migration/rollback compatibility.
- [ ] **Verify** MongoDB artifact persistence and cross-store source references.
- [ ] **Verify** Redis bounded/expiring state, outage behavior and absence of inappropriate clinical source-of-truth use.
- [ ] **Verify** Kafka topics/envelopes, partitions, consumer offsets, retention, producer retries and dead-letter/replay behavior.
- [ ] **Verify** MinIO initialization, private buckets, presigned access, encryption assumptions and lifecycle cleanup.
- [ ] **Verify** ClamAV readiness, unavailable scanner behavior and quarantine guarantees.
- [ ] **Verify** Elasticsearch readiness, index mappings, projections and rebuildability.
- [ ] **Verify** `api-migrate`, API health/readiness, graceful shutdown and dependency startup ordering.
- [ ] **Verify** `document-upload-cleanup`, `document-scanner`, `document-normalizer`, `document-ocr-worker`, `document-extraction-worker`, `document-promotion-worker` and `document-outbox-publisher` individually.
- [ ] **Verify** `triage-outbox-publisher`, `triage-timer-worker`, `summary-outbox-publisher` and `search-index-worker` individually.
- [ ] **Verify** all three frontend production containers and local development startup commands, ports, environment flags and API/WS URLs.
- [ ] **Verify** edge/gateway/TLS, CORS, upload/body limits, request deadlines and rate limits where configured; reconcile missing planned infrastructure.
- [ ] **Verify** backup/restore of clinical records, artifact/object recovery and cross-store reconciliation using disposable data.
- [ ] **Verify** measured latency, queue age, correlation IDs, readiness and incident runbooks; no PHI in metrics/traces/logs.

## 12. Security, privacy and audit

- [ ] **Implement** durable central audit where actions still use the in-memory emitter; existing durable search/identity/alert histories do not cover every workflow.
- [ ] **Verify** audit coverage for successful/denied access, consent, exports, signatures, identity administration and policy changes.
- [ ] **Verify** cross-patient/tenant/facility/role/purpose access matrix for every API, download, preview, WebSocket and worker-triggered operation.
- [ ] **Verify** request validation, file/content limits, dependency vulnerabilities, secrets handling and safe default feature flags.
- [ ] **Verify** authenticated responses and service workers cannot cache patient records or credentials on shared devices.
- [ ] **Verify** logs, traces, events and diagnostics contain neither raw clinical content nor credentials.
- [ ] **Reconcile** retention/deletion, backups, break-glass, consent delegation, encryption/key rotation and privacy incident requirements with actual controls.
- [ ] **External** privacy/residency/security approval and hospital identity/workforce verification require accountable external evidence.

## 13. Dead code and repository quality

- [ ] **Verify** imports, graph callers, route registrations, worker entry points, dynamic loading and feature flags before declaring code dead.
- [ ] **Verify** demo/in-memory session APIs and their callers; retire obsolete paths only after required functionality migrates.
- [ ] **Implement** migration of `apps/api/tools/seed_showcase.py` from the old kiosk-session endpoint and invented encounter to authenticated durable sessions.
- [ ] **Verify** duplicate modules, abandoned UI components, unused dependencies/assets, obsolete scripts and generated artifacts; preserve unrelated user changes and excluded TTS work.
- [ ] **Verify** restored summary modules remain canonical and no stale duplicate path is used at runtime.
- [ ] **Verify** formatting, lint, types, build scripts, lockfiles, dependency pins and CI coverage for changed apps/services.
- [ ] **Verify** skipped tests individually: enable applicable integration suites and document external-only or deliberately excluded cases.

## 14. Accessibility and showcase completion

- [ ] **Verify** Hindi/English text, language switching without data loss, readable question labels and patient comprehension of confirmation/errors.
- [ ] **Verify** keyboard-only navigation, focus order/return, screen-reader names, announcements, contrast, zoom/reflow and large touch targets across all dashboards.
- [ ] **Verify** mobile/tablet/desktop layouts, long translated text, evidence wrapping and loading/empty/error/disabled states.
- [ ] **Verify** clear manual alternatives for ASR/OCR failures; TTS/audio prompt implementation remains excluded.
- [ ] **Verify** one reproducible synthetic showcase dataset and reset procedure through public APIs without fake clinical outcomes or fabricated operational metrics.
- [ ] **Verify** latest production builds through the complete patient, nurse, doctor and admin browser journeys, including negative/failure cases.
- [ ] **Verify** SETUP contains tested PowerShell commands and absolute local paths for backend, every dashboard and required workers; resolve port/environment conflicts.
- [ ] **Verify** final evidence ledger links commands, outcomes, model/runtime configuration and bounded evaluation results.
- [ ] **Verify** final requirement-by-requirement audit proves completion of the agreed engineering scope; leave genuinely external approvals explicitly pending rather than claiming production/clinical readiness.

## 15. Roadmap/external integration disposition still to review

These are plan requirements to classify, not claims that they must all be production-deployed for a local showcase.

- [ ] **Reconcile / External** ABDM sandbox ABHA linking, HIP/HIU consent/callback/reconciliation and non-mandatory enrollment against the adapter and available sandbox credentials.
- [ ] **Reconcile / External** HPR/HFR, hospital SSO, HIS/LIMS/PACS integration and workforce/facility onboarding boundaries.
- [ ] **Reconcile / External** SMS/WhatsApp delivery, approved templates/opt-in and provider failure runbooks.
- [ ] **Reconcile / External** hospital pilot measurements, clinical safety approval, intended-user usability studies and consented evaluation datasets.
- [ ] **Reconcile** multi-facility scaling, autoscaling, disaster recovery/regional failover and advanced specialty assistance against explicit roadmap deferrals and current product scope.

## Source register

- [Review evidence ledger](FINAL-REVIEW-2026-09-06.md)
- [Build roadmap](../docs/plans/BUILD-ROADMAP.md)
- [Voice plan](../docs/plans/PHASE-4-VOICE-LAYER.md)
- [Dialogue plan](../docs/plans/PHASE-5-CLINICAL-DIALOGUE.md)
- [Triage plan](../docs/plans/PHASE-6-RED-FLAG-TRIAGE.md)
- [Document/OCR plan](../docs/plans/PHASE-7-DOCUMENT-INGESTION-OCR.md)
- [Summary plan](../docs/plans/PHASE-8-SUMMARY-WORKFLOW.md)
- [Patient dashboard plan](../docs/plans/PRE-PHASE-9-PATIENT-DASHBOARD-AND-S2S.md)
- [Search plan](../docs/plans/PHASE-9-SEARCH-RETRIEVAL-LONGITUDINAL-CONTEXT.md)
- [Identity contract](../docs/contracts/IDENTITY-API.md) and [patient contract](../docs/contracts/PATIENT-PORTAL-API.md)
- [Product scope](../docs/product/PRODUCT-SCOPE.md), [security/privacy](../docs/security/SECURITY-AND-PRIVACY.md), [clinical safety](../docs/safety/CLINICAL-AI-SAFETY.md)
- [Accessibility requirements](../docs/ux/ACCESSIBLE-WORKFLOWS.md), [operations](../docs/operations/SLOS-AND-RUNBOOKS.md), [resilience](../docs/operations/RESILIENCE-PATTERNS.md)

Suggested next implementation order: patient session completion → patient identity UI → governed alert delivery/handoff → admin dashboard → remaining pipeline/failure drills → accessibility and showcase verification → final evidence reconciliation.
