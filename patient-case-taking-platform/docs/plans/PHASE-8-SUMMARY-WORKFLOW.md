# Phase 8 — Evidence-linked clinical summary workflow

**Status:** Engineering candidate implemented and verified; no production or
clinical approval claimed

**Provider policy:** Mock provider only. Phase 8 must not download or call
HiMed-8B, vLLM, OpenAI, Claude, or any other remote or local generative model.

**Primary users:** triage nurse and doctor

## Delivery ledger

| Increment | Status | Required evidence |
| --- | --- | --- |
| 8.0 corrected scope and safety contract | Implemented | This plan and ADR-008 replace the unsupported supplied completion/provider claims. |
| 8.1 bounded context and deterministic generation | Implemented and unit-tested | Mock-only schema validation/fallback is reused; focused tests prove red-flag preservation, role rules and immutable lifecycle behavior. |
| 8.2 durable tenant-scoped workflow | Implemented and locally integration-tested | Migration 0012, forced RLS, optimistic concurrency, signed/action triggers, immutable history and reference-only outbox pass isolated-schema PostgreSQL tests. |
| 8.3 authorized lifecycle API | Implemented and contract-tested | Context confirmation, generate, read/list/history, edit, submit, reject, regenerate and sign pass role, facility, version and full-path API tests. |
| 8.4 source assembly | Implemented and locally integration-tested | Clinician-confirmed intake and server-recomputed triage join only active Phase 7 reviewed facts; client generation payload cannot inject narrative. |
| 8.5 doctor review experience | Implemented; external accessibility/usability evidence pending | API-backed empty/loading/error, evidence, edit, reject/regenerate, review/sign and version states lint and build. Formal assistive-technology testing remains pending. |
| 8.6 end-to-end and operational gates | Implemented engineering controls; external drills pending | Mock generate→edit→submit→sign and reject→regenerate paths, five live PostgreSQL tests including outbox delivery state, the metadata-only leased publisher and browser edit/review/sign smoke test pass. Production telemetry thresholds and recovery drills remain release gates. |
| 8.7 documentation and release evidence | Implemented; owner approvals pending | Setup, API, AI/safety, roadmap, event, runbook and HTML ledger documents match the mock-only implementation and measured checks. Clinical, privacy/security, accessibility, operations and facility approvals remain open. |

“Implemented” will mean repository behavior with passing engineering tests. It
will not mean clinical validation, regulatory compliance or production approval.

## 1. Review of the supplied Phase 8 document

The supplied `PHASE-8-COMPLETE.md` is treated as planning input, not evidence of
completed software. Its HiMed-8B/vLLM primary route and OpenAI/Claude tertiary
routes conflict with the explicit mock-only requirement. The claimed files,
accuracy, latency, acceptance, cost, compliance and clinical-validation results
are not established by this repository and must not appear as completed facts.

Useful intent retained from that document is limited to structured output,
evidence visibility, clinician review, versioning and safe fallback. Phase 8
does not install model weights, require API keys, transmit clinical context to
external inference, or silently switch providers.

## 2. Outcome

An authorized clinician can generate a structured summary draft from confirmed
encounter evidence, inspect the evidence behind it, edit it, reject and
regenerate it, submit it for review and sign an immutable version. The summary
is decision support, never autonomous diagnosis or an unsigned clinical record.

The first complete slice is:

> Confirmed intake and triage data become a mock-generated, evidence-linked
> draft that a doctor edits, reviews and signs without losing version history.

## 3. Scope

### Must deliver

- one schema-constrained `mock` provider plus deterministic template fallback;
- server-side assembly of only confirmed intake, triage and reviewed facts;
- explicit source references for every generated section;
- durable tenant/facility/patient/encounter ownership with PostgreSQL RLS;
- lifecycle `draft -> in_review -> signed` and `draft|in_review -> rejected`;
- regeneration as a new version rather than mutation of history;
- optimistic concurrency for every mutation and an immutable action ledger;
- signed-content hash and lock after sign-off;
- doctor-facing accessible evidence/edit/reject/regenerate/sign workflow;
- PHI-safe audit/event metadata and tested manual fallback.

### Out of scope

- diagnosis, treatment or medication recommendations;
- automatic sign-off, autonomous record promotion or red-flag suppression;
- local model downloads, GPU serving, vLLM or hosted model APIs;
- unreviewed OCR text as clinical truth;
- post-signature mutation (a separately governed addendum is future work);
- claims of HIPAA/DPDP compliance, clinical accuracy or production readiness.

## 4. Safety, privacy and accessibility invariants

1. The API constructs clinical context; a client cannot inject authoritative
   facts or omit deterministic red flags.
2. Only confirmed intake answers, current triage results and Phase 7 reviewed
   facts may be summarized. Raw OCR remains excluded.
3. Every statement carries an opaque source type and source identifier/path.
   Missing or conflicting evidence is surfaced as uncertainty, not invented.
4. Phase 6 deterministic red flags remain authoritative and visible. Summary
   generation cannot lower urgency or suppress emergency messaging.
5. Provider output is untrusted and schema validated. Failure returns a marked
   deterministic fallback that still requires clinician review.
6. Ordinary logs, metrics, audit records and outbox events contain IDs, status,
   versions, provider name and error class—not narrative clinical content.
7. Signed content is immutable. The signature binds canonical content, version,
   clinician identity and timestamp; it is integrity evidence, not legal proof.
8. Tenant and facility scope is enforced at authorization and database layers.
   Missing and cross-tenant records are indistinguishable to callers.
9. Editing, rejecting and signing are keyboard accessible, have explicit labels
   and expose status/errors through accessible live regions.
10. Mock-only is fail closed: any provider configuration other than `mock`
    prevents summary generation rather than downloading or calling a model.

## 5. Domain and lifecycle

Each summary version records tenant, facility, patient, encounter, lineage,
status, structured content, evidence references, red flags, uncertainties,
provider/schema metadata, degraded state, optimistic version, actors and
timestamps. Append-only revisions record action and metadata but no narrative.

Allowed transitions:

- `generate`: create version 1 in `draft`;
- `edit`: replace editable structured fields in `draft`, increment lock version;
- `submit-review`: `draft -> in_review`;
- `reject`: `draft|in_review -> rejected` with a bounded reason;
- `regenerate`: create a new `draft` linked to the prior version; the prior
  version remains immutable and marked superseded where appropriate;
- `sign`: doctor-only `in_review -> signed`, storing the signed hash.

Signed and rejected versions cannot be edited or submitted. A stale expected
version returns a conflict. Repeating an idempotent command returns its original
result or a conflict when the payload differs.

## 6. API contract

The durable surface is `/api/v1/summary-workflows`:

- `POST /generate`
- `GET ?encounter_id=...`
- `GET /{summary_id}`
- `PATCH /{summary_id}/draft`
- `POST /{summary_id}/submit-review`
- `POST /{summary_id}/reject`
- `POST /{summary_id}/regenerate`
- `POST /{summary_id}/sign`
- `GET /{summary_id}/history`

Commands carry `expected_version`; creation/regeneration carries an
`Idempotency-Key`. Responses expose evidence and safety metadata needed by the
review screen, but audit/event messages expose reference-only metadata.

Nurses may generate, read and submit drafts. Doctors may additionally edit,
reject, regenerate and sign. Facility access is required for every operation.

## 7. Architecture and storage

- Existing Phase 5 `LLMRouter` and `MockClinicalProvider` remain the sole
  generation boundary and provider.
- A summary context assembler loads verified encounter sources and maps them to
  the existing structured summary schema.
- A summary service owns transitions, authorization-independent domain rules,
  canonical hashing and immutable history.
- An in-memory repository supports isolated contract tests. A PostgreSQL
  repository is the durable runtime implementation.
- Migration `0012` owns summary versions, append-only actions, indexes, forced
  tenant RLS and reference-only outbox delivery state.
- The clinician console calls only the durable authenticated API; the existing
  demo clinical-summary route remains clearly labelled non-Phase-8 and gated.

## 8. Implementation increments

### 8.0 — Contract and governance

Publish this corrected plan, remove unsupported provider/compliance claims from
active setup and roadmap guidance, and define explicit external approval gates.

### 8.1 — Generation core

Add versioned request/response contracts, bounded context assembly, provenance
validation and deterministic fallback. Test malformed provider output, missing
evidence, red flags and the fail-closed provider policy.

### 8.2 — Persistence

Add migration, repositories, RLS, concurrency, idempotency and immutable
history. Test rollback, tenant isolation and signed-record immutability both in
unit tests and against the Compose PostgreSQL service.

### 8.3 — Workflow API

Expose the lifecycle endpoints with current-user and facility checks. Add API
tests for every role, transition, stale version, replay and cross-tenant access.

### 8.4 — Authoritative sources

Connect confirmed intake, triage and reviewed Phase 7 facts. Reject raw or
client-asserted evidence. Verify deterministic red flags remain in every draft.

### 8.5 — Clinician console

Replace the static doctor demo with API-backed states: loading, empty, draft,
in review, rejected, signed and failed/degraded. Keep evidence adjacent to each
section and make all actions keyboard and screen-reader usable.

### 8.6 — Full workflow and operations

Test generate → edit → submit → sign and reject → regenerate paths. Add safe
metrics, alert/runbook guidance, kill switch/manual fallback and recovery tests.

### 8.7 — Documentation and release gates

Update README, setup, API, AI/safety documentation, event catalog, roadmap,
`todo.json`, `whatsdone.md` and the HTML change ledger with exact commands and
measured evidence. Record remaining clinical, privacy/security, accessibility,
operations and facility approvals as pending.

## 9. Verification gates

- API format/lint/type checks used by the repository;
- focused Phase 8 unit and API tests;
- live PostgreSQL migration/repository integration tests through Docker Compose;
- full backend test suite;
- clinician-console lint and production build;
- browser workflow and accessibility smoke test with synthetic data;
- `docker compose config` and documented mock-only startup;
- `git diff --check` and an implementation-ledger audit.

No benchmark, acceptance rate, clinical accuracy or compliance statement may be
added without a named dataset, protocol, sample size, result artifact and owner
approval. Until those gates exist, Phase 8 is an engineering candidate only.
