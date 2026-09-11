# Phase 7 — Safe document ingestion, OCR and reviewed extraction

**Status:** Engineering candidate implemented and locally integration-tested;
clinical, privacy/security, accessibility, operations and facility approvals remain pending

**Depends on:** authenticated tenant/actor context, consent and purpose checks,
durable PostgreSQL workflow state, transactional outbox, private object storage,
malware scanning, and the project safety rule that unreviewed artifacts cannot
become clinical truth

**Primary users:** patient/caregiver, assisted kiosk operator, triage nurse,
doctor, health-information staff, clinical-safety owner, and operator

## Delivery status

| Increment | Status | Evidence |
| --- | --- | --- |
| 7.0 governance, hazards and evaluation fixtures | Engineering artifacts implemented; owner approval pending | Synthetic frozen prescription fixtures, provenance, null release thresholds, hazard log and approval record exist. No owner approval is recorded. |
| 7.1 registry, authorization and quarantine upload | Implemented and locally integration-tested | Eleven repeatable migrations, forced tenant RLS, active consent/purpose authorization, idempotent registration/finalization, private MinIO upload, abandoned-session expiry and reference-only outbox are tested. Production object encryption/role policy remains an external gate. |
| 7.2 malware scan and normalization | Implemented and locally integration-tested | Pinned ClamAV service, quarantine promotion, bounded PDF/image normalization, immutable page artifacts and failure events are covered by unit and live-service tests. |
| 7.3 versioned OCR | Implemented with PP-OCRv5 runtime plus deterministic test provider | The dedicated worker image contains PaddlePaddle/PaddleOCR, defaults to real CPU PP-OCRv5, and stores durable PostgreSQL runs plus immutable MongoDB page/region provenance. Representative camera/handwriting clinical validation remains pending. |
| 7.4 narrow prescription extraction | Implemented as deterministic candidate | Durable immutable drafts/candidates, explicit context flags, source geometry, retry/DLQ and a seven-fixture synthetic evaluation are implemented. Lab extraction remains deliberately deferred. |
| 7.5 source-adjacent review | Implemented; external accessibility/usability evidence pending | Nurse/doctor queue, short-lived page preview, accept/correct/reject/unreadable/rescan/defer/manual entry, optimistic concurrency, append-only decisions and bilingual keyboard-first UI are tested. |
| 7.6 reviewed-fact promotion | Implemented and locally integration-tested | Only accepted/corrected candidates become authoritative facts; timeline/FHIR/search projections are rebuildable; withdrawal preserves history. |
| 7.7 delivery, operations and rollout | Engineering controls implemented; controlled rollout not approved | Kafka outbox publisher, bounded delivery retry/dead-letter, aggregate operations status, OCR/extraction kill switches, manual fallback and runbook exist. Staging drills, representative evaluation and owner approvals remain pending. |

This table is the implementation ledger. “Implemented” describes repository
behavior, not clinical validation or production approval.

## 1. Outcome

Phase 7 will let an authorized user upload a clinical document into quarantine,
preserve the immutable source, process it asynchronously, and present
page/region-linked OCR and structured extraction drafts for human review. Only
explicitly accepted facts may be promoted into the authoritative clinical
record or longitudinal timeline.

The first end-to-end outcome is the roadmap slice:

> An uploaded prescription becomes a reviewed structured document with every
> accepted field traceable to the source object, page and region.

OCR output is untrusted evidence, not a diagnosis, medication order, verified
lab result, signed record, or safe input to deterministic triage. A model,
dictionary match, confidence score, or document label cannot bypass review.

## 2. Review of the supplied Phase 7 document

The supplied `PHASE-7-COMPLETE.md` was planning material, not implementation or
validation evidence. At review time its completion status and the following
claims were unsupported. This historical gap analysis is retained so later code
is not confused with the supplied claims:

- `ocr_pipeline.py`, `document_classifier.py`, `entity_extractor.py`, the
  claimed ontology JSON files, and their stated paths do not exist.
- No custom Hindi-handwriting CRNN, ResNet-18 document classifier, medical
  entity extractor, timeline generator, or clinician review workflow exists.
- No evidence supports the claimed printed/handwritten accuracy,
  classification accuracy, entity accuracy, latency, throughput, or composite
  confidence values.
- No governed datasets or approvals support claims involving 500
  prescriptions, 200 lab reports, 100 discharge summaries, or clinician
  validation.
- The earlier demo OCR API accepted a single image and had none of the durable
  workflow controls. The Phase 7 path is now separate, gated by
  `DOCUMENT_WORKFLOW_ENABLED`, and the demo route does not count as Phase 7 evidence.
- Compose includes local MinIO, but the OCR route does not store uploaded files
  there and does not prove encryption, RBAC, retention, legal hold, deletion,
  backup expiry, or audited object access.
- “DPDP compliant” cannot be inferred from code structure or general consent.
  Purpose, notice, data minimization, authorization, retention, processor
  arrangements, data-principal rights, and operational controls require
  governance and evidence.
- A seven-year retention period is not assumed. Retention is approved per
  artifact class and facility policy, including withdrawal effects, legal hold,
  deletion/anonymization, and backup expiry.

The supplied file must not be copied into the repository as a completion
report. This plan replaces its unsupported status and preserves only useful
ideas that can pass the project’s safety and evidence gates.

## 3. Verified foundation to reuse

| Existing boundary | Verified behavior | Limitation |
| --- | --- | --- |
| `apps/api/app/ocr/base.py` | Provider-neutral `OCRProvider`, `OCRResult` and region contract. | In-memory result only; no page/artifact identity or schema version. |
| `apps/api/app/ocr/registry.py` | Fail-closed selection of mock, PP-OCRv5 or PaddleOCR-VL providers. | No policy router by document class, quality or approved model version. |
| `apps/api/app/ocr/fast_paddle_provider.py` | PP-OCRv5 adapter with normalized text, score and bounding boxes; installed in the dedicated OCR worker image. | Real inference implementation, but not a validated clinical extraction pipeline. |
| `apps/api/app/ocr/paddle_provider.py` | Lazy PaddleOCR-VL complex-layout adapter. | Very heavy fallback; no admission control, durable job or clinical validation. |
| `apps/api/app/routers/ocr.py` | Demo-gated, bounded upload/base64 endpoints; MIME allowlist, empty/size checks and sanitized failures. | Single-image synchronous prototype; raw OCR text is returned directly to the caller. |
| OCR tests | Provider-contract, payload-normalization and bounded-route tests. | Do not establish field accuracy, handwriting quality, tables, multi-page behavior or review safety. |
| Architecture documents | `document_registry`, object quarantine, MongoDB OCR artifacts, outbox events and reviewed-fact promotion are already assigned owners. | Conceptual only; no migrations, repositories, workers or integration proof. |

The mock provider remains available for isolated contract tests. The Compose
document worker defaults to real PP-OCRv5 as the printed-text provider;
PaddleOCR-VL is a separately measured
complex-layout candidate. A Hindi handwriting model is not selected until its
dataset provenance, license, quality, hardware and failure behavior are
evaluated.

## 4. Goals and non-goals

### Must deliver

- authorized, idempotent direct-to-quarantine upload;
- immutable source checksum and durable document registry state;
- malware/type/size validation before clinical processing;
- asynchronous page normalization and OCR with versioned provider metadata;
- page, region and source-object provenance for every OCR span and entity draft;
- clinician/staff correction, accept and reject workflow;
- promotion of reviewed facts only;
- PHI-safe events, logs, metrics and failure handling;
- deterministic fallback to manual document review when automation fails.

### Should deliver after the first prescription slice

- printed lab-report extraction with table and unit-aware review;
- multi-page image/PDF support after decompression and parser-abuse controls;
- document quality feedback and assisted recapture;
- reviewed-fact timeline projection;
- language/document-class routing based on measured evidence.

### Out of scope for this phase

- autonomous diagnosis, prescription reconciliation, medication ordering or
  clinical decision-making;
- automatic promotion based on confidence thresholds;
- raw OCR or extracted diagnoses directly changing Phase 6 triage priority;
- similarity search, RAG or external-LLM processing of uploaded documents;
- a custom handwriting model without a governed training/evaluation program;
- insurance adjudication, ABDM production exchange, or final FHIR conformance;
- claiming compliance, legal retention, or accuracy without reviewed evidence.

## 5. Safety and privacy invariants

1. The original upload is immutable and checksummed; derived pages, thumbnails,
   overlays and OCR artifacts reference it and never replace it.
2. Files enter a private quarantine prefix. They cannot reach OCR, clinical
   storage or download surfaces until type, size and malware policy passes.
3. Authorization is checked when upload is initiated, when an object is read,
   when processing starts, and when a reviewer acts. Object URLs are short-lived
   and scoped; buckets are never public.
4. PostgreSQL owns registry/job/review state. Object storage owns binaries.
   MongoDB may own versioned OCR/layout/extraction artifacts but never signed or
   accepted clinical truth.
5. Every OCR span retains document version, object checksum, page, bounding
   region, provider/model version, preprocessing version and processing run ID.
6. Provider confidence is nullable unless the provider supplies a documented
   score. OCR score, parser validity and clinical correctness are separate
   signals; do not invent a composite “overall confidence.”
7. Low score, missing score, conflicting extraction, unreadable content,
   ambiguous abbreviations and unit mismatch require review or manual entry.
8. OCR text and document contents are untrusted data. They cannot become system
   instructions, choose models, alter authorization, or suppress safety rules.
9. Raw OCR/extracted facts cannot trigger a critical triage alert. A patient or
   authorized clinician must confirm the relevant structured fact first.
10. Accepting one field does not accept the entire document. Review decisions
    are field/version specific and keep the original extraction visible.
11. Events and ordinary logs contain opaque IDs, checksums, versions, status and
    error class—not images, raw OCR text, names, identifiers, diagnoses or lab
    values.
12. Deletion, retention and legal hold operate from approved policy and preserve
    an auditable lifecycle without promising impossible immediate backup erasure.

## 6. User requirements

### Patient or caregiver

- Explain why the document is requested and what will happen to it.
- Provide camera/gallery/file choices only after purpose and consent checks.
- Show framing, glare, blur, crop and multi-page guidance in Hindi and English.
- Allow cancel before submission and display upload/processing/review status.
- Never display extracted medication, diagnosis or result as verified before a
  clinician/staff reviewer accepts it.

### Assisted kiosk operator or nurse

- Attribute who uploaded/scanned the document and for which encounter/purpose.
- Re-capture a poor page without deleting the original attempt.
- See quarantine, scan, OCR, review and failure states with actionable fallback.
- Compare each draft field with a source-region crop and correct or reject it.

### Doctor

- Review accepted/rejected/corrected facts and their provenance beside the
  clinical note.
- Distinguish document-stated diagnoses/medications from clinician-verified
  current facts.
- Promote only selected reviewed facts; signing remains a separate decision.

### Operator and governance reviewer

- Monitor queue age, failures, malware rejections, provider/model version,
  unreadable rate, correction rate, replay and dead-letter state without PHI.
- Audit upload, access, processing, review, promotion, export and deletion/legal
  hold actions by actor, facility, purpose and resource.

## 7. Canonical contracts and ownership

### Document registry aggregate

The PostgreSQL `document_registry` aggregate contains at minimum:

- internal document UUID, tenant/facility/patient/encounter scope and version;
- uploader actor/type, purpose, consent/legal-basis reference and idempotency key;
- original filename as protected metadata, declared/detected MIME, size and
  checksum;
- private object ID, storage class and retention-policy reference;
- document class as `declared`, `suggested` and `reviewed` values, never one
  silently overwritten field;
- current state, rejection/failure code, active processing run and timestamps;
- optimistic concurrency version and audit/outbox linkage.

Recommended states:

`initiated → uploaded → quarantined → scanning → scan_rejected | scan_passed → processing → review_required → reviewed`

`processing_failed`, `cancelled`, `retention_hold` and `deletion_pending` are
explicit governed states. Illegal transitions fail closed. Retrying processing
creates a new run; it does not mutate an old artifact.

### Upload contract

1. Client requests an upload session with encounter, purpose, declared type,
   filename metadata, size, MIME and idempotency key.
2. API authorizes scope and returns a short-lived single-object upload grant for
   a quarantine key plus exact size/type/checksum requirements.
3. Client uploads directly to object storage and calls finalize with checksum.
4. API verifies object metadata/checksum, commits registry state plus outbox, and
   never trusts filename extension or browser MIME as detected type.
5. Scanner consumes only the opaque object reference with scoped read access.

Initial allowlist: PDF, PNG, JPEG and WebP only after parser and decompression
limits are implemented. The existing synchronous endpoint remains demo-only and
is not the production upload path.

### OCR artifact envelope

`DocumentOcrArtifact.v1` contains:

- artifact/run/document/page IDs and source checksum;
- provider, model, language-pack and preprocessing versions;
- page dimensions, orientation and quality signals;
- ordered regions with bbox/polygon, text, nullable provider score, script and
  reading order;
- normalized full-page text as a protected artifact, not an event payload;
- warnings, error class, duration and review requirement;
- schema version and created timestamp.

Large/raw artifacts live in object storage or MongoDB under authorized access.
PostgreSQL stores stable references and status.

### Extraction draft

`DocumentExtractionDraft.v1` contains typed candidates rather than one free-form
clinical JSON object. Every candidate has:

- entity ID/type and document class;
- raw-source region refs and normalized candidate value;
- parser/model/rules version;
- nullable model/parser signals kept separate;
- negation, temporality, subject and uncertainty where applicable;
- unit and reference-range source for lab values;
- review state: `unreviewed`, `accepted`, `corrected` or `rejected`;
- reviewer/correction provenance after action.

Start with a narrow prescription schema: document date, medication-statement
text, strength, route, frequency, duration and instructions. Store what the
document states; do not infer that the patient currently takes it. Add lab fields
only after table/units/reference-range evaluation. Diagnoses and procedures
remain document statements until a clinician verifies them.

### Events

Reuse the existing standard envelope and event catalog. Existing events keep
their names; new lifecycle events require contract review before implementation:

- existing `DocumentUploaded.v1`, emitted only after upload finalization;
- implemented `DocumentScanCompleted.v1`;
- existing `ai.ocr.requested.v1` and `ai.ocr.completed.v1`;
- existing `DocumentProcessingCompleted.v1`, emitted after the referenced OCR
  and extraction artifacts are durably persisted;
- implemented `DocumentReviewCompleted.v1`;
- implemented `ReviewedDocumentFactsPromoted.v1`.

Registry state and outbox are committed in one PostgreSQL transaction. Consumers
use a processed-event ledger and artifact/run uniqueness constraints. Retries are
bounded; terminal failures enter a PHI-safe dead-letter workflow. No event
contains document bytes or raw OCR/entity values.

## 8. End-to-end workflow

1. Authorized user starts an upload for an encounter and approved purpose.
2. Browser uploads directly to a private quarantine object using a scoped grant.
3. Finalization verifies checksum/size and commits registry plus outbox state.
4. Scanner detects actual type, archive/parser abuse and malware. Failure keeps
   the object isolated and presents a safe recapture/manual path.
5. Page normalizer creates versioned derivatives without changing the original.
6. OCR worker chooses only an approved provider for the page class/language and
   records page/region provenance.
7. Extraction worker produces typed candidates from the protected OCR artifact.
8. Reviewer compares candidates with source crops, then accepts, corrects or
   rejects each field using optimistic concurrency and an idempotency key.
9. Clinical platform promotes selected reviewed facts to PostgreSQL with full
   provenance and emits a reference-only event.
10. Timeline/FHIR/search projectors consume only reviewed authoritative facts;
    they remain disposable projections and never become the source of truth.

If Kafka, OCR, extraction or object preview fails, the durable registry retains
the accepted upload and exposes manual review/retry. A model failure never loses
the source document or blocks ordinary clinician note entry.

## 9. Delivery slices

### Slice 7.0 — governance, hazards and evaluation fixtures

- Name document workflow, clinical-safety, privacy and operations owners.
- Approve upload purpose/notice, allowed document classes, source retention,
  reviewer roles, malware response and manual fallback.
- Build synthetic or appropriately governed de-identified fixtures across clean,
  noisy, rotated, photographed, Hindi, English, code-switched, table, handwriting
  and adversarial/prompt-injection cases.
- Record provenance, license, permitted use, adjudication and expected page/field
  truth for every fixture.

**Gate:** no clinical document processing with real patient data before this
review and the storage/access boundary are approved.

### Slice 7.1 — durable registry and quarantine upload

- Add document registry/outbox migrations, repository, state machine,
  idempotency/checksum uniqueness and audit actions.
- Implement authorized upload-init/finalize/status/cancel APIs and direct private
  object upload with short-lived grants.
- Verify magic bytes, actual MIME, size, checksum and parser/decompression limits.
- Implement quarantine prefixes, deny-by-default object policy and expiry of
  abandoned sessions.

**Gate:** cross-tenant denial, checksum mismatch, spoofed MIME, oversized/decompression
bomb, duplicate finalize, abandoned upload, object denial and rollback tests pass.

### Slice 7.2 — malware scan and page normalization

- Add an isolated scanner worker with pinned signature/engine version and
  reference-only scan results.
- Promote only scan-passed objects to a clinical-processing prefix.
- Normalize orientation/crop/deskew/contrast as versioned derivatives; retain
  the original and processing parameters.
- Add page-count, pixel, memory, CPU and deadline admission limits.

**Gate:** malicious/unknown/error results remain quarantined; retry, engine
outage, timeout and operator-resolution paths are tested.

### Slice 7.3 — versioned OCR worker

- Extend the OCR contract with page/artifact/run identity and schema version.
- Run PP-OCRv5 as the initial printed-text candidate; use PaddleOCR-VL only for
  an approved complex-layout class after measured routing benefit.
- Keep handwriting in manual review until a specialist candidate passes dataset,
  license, quality, latency, memory and rollback evaluation.
- Persist OCR/layout artifacts before publishing completion; add idempotent
  retries, DLQ, replay and PHI-free metrics.

**Gate:** frozen page fixtures, provider failures, duplicate jobs, worker crash,
broker outage and artifact-store denial prove no accepted document is lost.

### Slice 7.4 — narrow typed extraction

- Implement prescription candidate extraction with explicit negation,
  temporality, subject and abbreviation handling.
- Separate deterministic parsing from any model output and retain both versions.
- Add lab-report extraction only after robust table, units, decimal, reference
  range, abnormal-flag and locale tests.
- Do not emit diagnosis codes automatically; terminology mappings remain
  suggestions with source and version.

**Gate:** field-level exact-match/F1, unsupported assertion, unit, negation,
temporality and source-link results meet owner-approved thresholds on frozen data.

### Slice 7.5 — source-adjacent review workflow

- Build nurse/doctor work queue with document/processing status and stale time.
- Show page image and highlighted source region beside every candidate.
- Add accept, correct, reject, unreadable, request-rescan and defer actions with
  keyboard/screen-reader support and optimistic concurrency.
- Persist append-only review history and PHI-minimized audit metadata.

**Gate:** bilingual usability/accessibility, concurrent reviewer, stale artifact,
partial acceptance, source-preview failure and manual-entry tests pass.

### Slice 7.6 — reviewed-fact promotion and timeline

- Promote only accepted/corrected fields through the clinical platform into
  authoritative PostgreSQL records with provenance.
- Build timeline and FHIR/search projections from reviewed facts, with document
  statement vs clinician-confirmed-current status visible.
- Keep signature/clinical-note workflow separate from document review.

**Gate:** rejected/unreviewed fields never appear as clinical truth; replay,
correction, withdrawal/retention and projection rebuild tests pass.

### Slice 7.7 — validation, operations and controlled rollout

- Benchmark by document class, language/script, capture source, quality, page
  type and provider on recorded reference hardware.
- Measure review correction, unreadable/rescan, false extraction and source-link
  failure rates—not just OCR text accuracy.
- Add dashboards/runbooks for queue age, scan rejection, processing failures,
  model version, DLQ, object access, review backlog and promotion errors.
- Canary by facility/document class with a kill switch that preserves upload and
  manual review while disabling automated OCR/extraction.

**Gate:** clinical safety, privacy/security, accessibility, operations and
facility owners approve the evidence and rollback/restore drill.

## 10. Verification matrix

| Area | Required evidence |
| --- | --- |
| Upload/security | Authz scope, purpose/consent, magic-byte/MIME mismatch, checksum, size/page/pixel/decompression limits, malicious file, object-policy and short-lived URL tests. |
| Registry/workflow | Legal transitions, optimistic concurrency, idempotency, duplicate finalize, cancellation, retry, retention hold and audit/outbox atomicity. |
| OCR | Page/region provenance, order, bbox/polygon, nullable provider score, Hindi/English/code-switch, rotation, blur, glare, tables, handwriting and unreadable fallback. |
| Extraction | Field exact match/F1, units, decimal/locale, abbreviation, negation, temporality, subject, unsupported assertion and evidence-link correctness. |
| Review | Partial acceptance, correction/rejection, concurrent actor, stale version, source preview unavailable, keyboard/screen reader and bilingual comprehension. |
| Events/resilience | Transaction rollback, duplicate delivery, retry/DLQ/replay, broker/worker/object-store failure, schema compatibility and PHI payload scanner. |
| Promotion | Only reviewed fields reach PostgreSQL/timeline/FHIR/search; correction and projection rebuild preserve provenance. |
| Operations | Reference-hardware percentiles, queue age, saturation, recovery, backup/restore, deletion/hold and rollback drill. |

All ordinary development and CI fixtures are synthetic. Real documents require
separate authorization, minimization, de-identification where possible, access
controls, approved retention and governance/ethics review.

## 11. Metrics: targets are not achievements

| Signal | Required reporting position |
| --- | --- |
| OCR quality | Report character/word error and region detection separately by document class, language/script, capture quality and provider, with confidence intervals. |
| Handwriting | No target until a governed dataset and candidate exist; report writer/site splits to prevent leakage. |
| Document classification | Prefer declared + reviewer-confirmed class initially. Any automated candidate reports per-class precision/recall/confusion matrix and abstention. |
| Extraction | Report field-level precision/recall/F1, exact match, unit/negation/temporality errors and unsupported assertions. |
| Source linking | Measure correct document/page/region linkage independently; target and threshold require clinical-safety approval. |
| Latency/throughput | Record page count, resolution, provider/model, hardware, cold/warm state, concurrency and p50/p95/p99; do not copy “under 3 seconds.” |
| Human workflow | Measure correction, rejection, unreadable, rescan, review time, backlog age and material-error escape rate. |
| Durability | Every accepted upload has registry, checksum and outbox reconciliation; no lost/duplicate promotion is tolerated. |

No result is “achieved” until a reproducible report identifies commit, provider
and model versions, dataset/provenance, environment, method, sample size,
subgroups, result, limitations, reviewer and date.

## 12. Failure behavior and rollback

- Upload unavailable: allow ordinary intake; do not block care.
- Scan rejected/unknown: keep isolated, show non-sensitive reason and offer
  recapture/manual workflow; never process or download through normal UI.
- OCR unavailable/timeout: retain durable pending state, bounded retry, then
  manual review; never return an empty extraction as success.
- Low/missing score or unreadable page: show source and request rescan/manual
  entry; do not auto-promote.
- Extraction unavailable: allow raw OCR/source review and manual structured entry.
- Object preview unavailable: block field acceptance that requires unviewable
  evidence unless an approved manual source-verification path is recorded.
- Kafka unavailable: outbox retains work; status shows delayed and reconciliation
  confirms dispatch after recovery.
- Bad provider/model release: disable that version, preserve artifacts, requeue
  eligible documents with original idempotency lineage, and keep manual review.
- Rollback never deletes accepted review history or source documents outside an
  approved retention/deletion workflow.

## 13. Exit criteria

Phase 7 may be called complete only when:

- an authorized upload moves through durable registry, quarantine, scan,
  processing and review states without losing the immutable source;
- object storage, PostgreSQL, MongoDB artifact and outbox ownership match the
  architecture and pass tenant/facility isolation tests;
- every OCR span/entity candidate retains source-object/page/region and
  provider/parser/model provenance;
- clinicians can correct, accept and reject individual candidates beside the
  source, with append-only review history;
- only reviewed facts enter the authoritative record or timeline;
- manual document review remains available during scanner, broker, OCR,
  extraction or preview failure;
- events/logs/metrics/notifications pass PHI-content checks;
- security testing covers malicious files, parser/decompression abuse, object
  access and cross-tenant references;
- accessibility/usability evidence covers patient capture and staff review;
- reproducible OCR/extraction validation reports include failures and subgroup
  results, and meet thresholds approved before evaluation;
- retention, legal hold, deletion, consent/purpose and processor policies are
  approved and operationally tested;
- backup/restore, replay/reconciliation, incident and provider rollback drills
  pass in staging;
- clinical safety, facility operations, privacy/security, accessibility and
  engineering owners record approval.

Until those gates pass, repository and review material must say **candidate**,
**prototype**, **in progress** or **not implemented**—never “clinically
validated,” “DPDP compliant,” “all targets met” or “production ready.”

## 14. Suggested pull-request sequence

1. `docs(phase7): approve document contracts, hazards and validation protocol`
2. `feat(documents): add durable registry and quarantine upload`
3. `feat(documents): add scan and page-normalization worker`
4. `feat(ocr): persist versioned page and region artifacts`
5. `feat(extraction): add reviewed prescription candidates`
6. `feat(ui): add source-adjacent document review`
7. `feat(records): promote reviewed facts and rebuildable timeline`
8. `test(phase7): publish resilience, accessibility and validation evidence`

Every executable slice stays behind deny-by-default facility/document-class
policy. Disabling automation must preserve source access and manual review, and
must never hide already accepted facts or review history.
