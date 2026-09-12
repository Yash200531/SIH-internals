# OpenCode Change Review — Verified Record

Reviewed on 2026-08-29. This file records evidence, not roadmap optimism.

## Accepted and improved

- Kept the three separate Next.js shells for patient kiosk, clinician console, and administration.
- Upgraded all shells from the vulnerable Next.js 14 baseline to Next.js 16.3.3 Active LTS with React 19, reproducible lockfiles, ESLint CLI configuration, standalone output, and non-root containers.
- Fixed the kiosk server/client callback build failure and invalid nested link/button markup.
- Kept the FastAPI domain prototype, corrected its packaging backend, added real dependency readiness probes, and made readiness return HTTP 503 when dependencies are unavailable.
- Replaced wildcard credentialed CORS with explicit origins, methods, and headers.
- Made all synthetic clinical, identity, consent, audit, AYUSH, and FHIR routes opt-in through `ENABLE_DEMO_ROUTES`; they are off by default.
- Corrected Kafka internal/external listeners, local-only port binding, dependency health checks, and local-development credential labeling in Docker Compose.
- Corrected GitHub Actions working directories and aligned its commands with the repository layout.
- Removed the duplicate `docs/adr` set; the canonical ADRs remain under `docs/architecture/decisions`.

## Verification performed

| Gate | Result |
|---|---|
| Patient kiosk lint + production build | Passed |
| Clinician console lint + production build | Passed |
| Admin console lint + production build | Passed |
| Frontend dependency audit | 0 known vulnerabilities in each lockfile |
| FastAPI Ruff check | Passed |
| FastAPI mypy check | Passed across 60 source files |
| FastAPI tests | 42 passed |
| Docker Compose config parse | Passed |
| GitHub Actions YAML parse | Passed |

## Explicitly not complete

This is a reviewed foundation prototype, not a production clinical system. Clerk token verification, durable repositories, database migrations, multi-tenant authorization, transactional audit, Kafka workflows, object-storage policy, ABDM sandbox integration, end-to-end browser tests, accessibility validation, load/security testing, deployment, backup/restore, and clinical governance remain pending.

The detailed visual review is in [`review/medikiosk-change-ledger.html`](review/medikiosk-change-ledger.html).

## Phase 8 — evidence-linked summary workflow (2026-09-04)

- Replaced the supplied unsupported completion/provider claims with an honest
  implementation plan and mock-only ADR-008.
- Added clinician-confirmed encounter context, server-side Phase 6 warning-rule
  recomputation and active reviewed-document-fact assembly.
- Added the mock-only structured generation boundary with deterministic fallback,
  evidence paths and warning-flag preservation.
- Added PostgreSQL migration 0012 for confirmed context, summary versions,
  append-only actions and reference-only outbox records with forced tenant RLS.
- Added optimistic concurrency, request-bound idempotency, immutable signing and
  atomic reject/regenerate lineage.
- Added authorized APIs for context confirmation, generation, list/read/history,
  draft editing, review submission, rejection, regeneration and doctor sign-off.
- Replaced the static doctor screen with an API-backed evidence/edit/review/sign UI.
- Added focused domain, HTTP and live PostgreSQL integration tests; clinician UI
  lint and production build pass.
- Added metadata-only summary event delivery with leases, bounded retry/backoff
  and dead-letter state on `clinical.summaries.v1`.
- Browser-tested synthetic local login, encounter loading, clinician edit,
  review submission and immutable doctor sign-off with a clean console.
- Updated setup, AI/safety, architecture, event, resilience and roadmap guidance
  to prohibit HiMed/vLLM downloads and OpenAI/Claude API use.

Phase 8 is an engineering candidate, not a production clinical system. Identity
hardening, owner approvals, representative clinical evaluation, accessibility,
production telemetry, load/security, backup/restore and rollback drills
remain release gates.

## Pre-Phase 9 — patient dashboard, services and real OCR (2026-09-05)

- Replaced the patient records placeholder with authenticated, token-derived
  `/patient-portal/me` dashboard, signed-report detail/download, reviewed timeline
  and patient-owned document status/upload services.
- Added durable patient treatment consent and confirmed intake decisions,
  including idempotent accept/reject persistence and cross-scope denial.
- Connected kiosk session creation, consent, confirmed voice/touch answers,
  adaptive mock-provider SOCRATES questions, accessible emergency interruption
  and deterministic mock TTS WAV playback.
- Kept HiMed-8B, vLLM, OpenAI and hosted inference out of the runtime.
- Corrected the OCR deployment truth: the document worker now has a dedicated
  PaddlePaddle/PaddleOCR image, defaults to the official PP-OCRv5 mobile detector
  and recognizer, warms before claiming work and persists model caches.
- Verified actual recognition inside that image: a generated prescription
  produced three regions and asserted `METFORMIN 500` successfully.
- Passed Ruff, mypy across 146 source files, 307 backend tests (22 gated skips),
  patient ESLint/production build, isolated live patient persistence and the live
  Phase 7 durable document-chain check.

This is an engineering candidate. Production patient identity, representative
OCR/clinical evaluation, intelligible production speech, accessibility/usability
sessions, security/privacy approval and operational recovery evidence remain
release gates.

## Phase 9 — reviewed-record search and longitudinal context (2026-09-06)

- Replaced the supplied completion narrative with an evidence-gated plan and
  ADR-010; unsupported million-record, latency and production-readiness claims
  were removed.
- Added strict search contracts, Unicode-safe lexical analysis, reviewed medical
  synonyms, opaque cursors, bounded escaped highlights and deterministic
  longitudinal assembly.
- Projected only doctor-signed summaries and active clinician-reviewed document
  facts. Raw OCR, extraction candidates and unsigned/rejected/superseded drafts
  cannot enter the search document contract.
- Added Elasticsearch 9.3 indexing/search/facets/delete, Kafka synchronization,
  idempotent replay, tenant repair and metadata-only reconciliation.
- Added migration 0014 and forced-RLS audit rows for search, timeline, FHIR and
  export; query text is stored only as SHA-256 and returned narrative is absent.
- Added role/facility/patient/purpose authorization, self-scoped patient timeline,
  doctor/patient CSV with formula neutralization, and supported FHIR search sets.
- Added a complete clinician search/timeline interface and bilingual patient
  longitudinal panel with direct canonical-record fallback.
- Browser-tested synthetic doctor, nurse and patient paths. The test found and
  repaired a real canonical SQL bind-count defect before this phase was labelled
  an engineering candidate.
- Added packaged tenant reconciliation/rebuild commands and a disposable,
  deterministic 250-record benchmark. Four English/Hindi golden queries passed,
  cross-tenant control held, and 250 canonical IDs reconciled to 250 indexed IDs.

Phase 9 remains an engineering candidate. Production Clerk/SSO identity,
representative relevance and multilingual evaluation, projected-scale load and
recovery testing, privacy/clinical/accessibility owner approvals, backup/restore
and staged rollback remain closed release gates.
