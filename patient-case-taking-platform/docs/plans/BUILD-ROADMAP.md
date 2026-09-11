# Build Roadmap

## Planning assumptions

- Initial pilot: one or two hospitals, Hindi and English, outpatient case-taking.
- AI assists documentation; it does not independently diagnose or prescribe.
- Patients may lack ABHA, smartphones, literacy or reliable connectivity.
- The first release should optimize safe workflow learning, not national-scale infrastructure.

## Current implementation milestone

The repository's **Phase 4–9 engineering slices are implemented**, including
the self-scoped patient services and rebuildable reviewed-record search. Phase 9
is an engineering candidate backed by real PostgreSQL/Kafka/Elasticsearch tests,
packaged rebuild/reconciliation tools and a small synthetic benchmark—not a
production or clinical-relevance approval. Exact evidence and remaining release
gates are recorded in the phase plans. Clinical dialogue/summary remains mock-only under
[ADR-008](../architecture/decisions/ADR-008-MOCK-ONLY-CLINICAL-SUMMARY.md);
patient self-scope and mock TTS are governed by
[ADR-009](../architecture/decisions/ADR-009-PATIENT-SELF-SCOPE-AND-MOCK-TTS.md).

## Approved stack baseline

- Next.js/React/TypeScript monorepo with separate patient, doctor and user-administration deployments.
- FastAPI for the modular clinical core, WebSocket gateway and Python-facing APIs.
- Clerk for staff/patient web authentication, with hospital SSO integration where available and a constrained kiosk pre-auth flow.
- Offline deterministic mock clinical provider plus safe template fallback; no generative model download or hosted LLM API.
- Existing ASR boundary, deterministic mock TTS, a real CPU PP-OCRv5 document
  worker with gated PaddleOCR-VL fallback, and reviewed-fact extraction. Real
  speech and representative OCR clinical quality still require approval.
- Versioned Python rules service for deterministic red flags and policies.
- PostgreSQL for transactional/clinical truth; MongoDB for raw transcript/OCR/model artifacts; Redis for ephemeral state; S3-compatible object storage for binaries.
- WebSockets for interactive updates; Kafka from MVP with durable PostgreSQL state/outbox, retries, DLQs and idempotent consumers.
- Elasticsearch 9.3 for rebuildable lexical search of signed summaries and
  reviewed facts; audit exploration, analytics and vector search remain outside
  the implemented slice and require representative evaluation.
- Docker for local deployables; shared pilot/production topology remains an external design gate.

## Phase 0 — Discovery, governance and contracts

Duration target: 3–5 weeks.

### Work

- Observe registration, consultation, upload and discharge workflows.
- Define patient, caregiver, receptionist, nurse and doctor journeys.
- Appoint clinical-safety, privacy and data-governance owners.
- Define internal patient identity, duplicate resolution and merge/unmerge rules.
- Validate Clerk privacy, residency, webhook, MFA, session-revocation and hospital-SSO requirements; document the replacement boundary.
- Define kiosk pre-auth capabilities and prove that anonymous sessions cannot search or display PHI.
- Define consent, retention, deletion, emergency access and audit policies.
- Select FHIR resource mappings and ABDM participation roles: HIP, HIU or both.
- Approve the API style, event envelope and service ownership map.
- Define edge route classes, TLS ownership, direct-upload limits and the public-gateway/internal-model-router trust boundary.
- Record and test the mock-only, no-external-inference policy.
- Define Kafka topic/envelope ownership, partition keys, schema compatibility, retention, retry tiers, DLQs and replay runbooks before implementation.
- Extend the current small Hindi/English lexical-search benchmark into a governed,
  representative relevance/load evaluation; filtered vector retrieval, licensing,
  residency, recovery and operating cost remain approval gates.
- Establish baseline metrics for consultation and documentation time.

### Exit gate

- Signed clinical workflow and hazard analysis.
- Approved information architecture and threat model.
- Synthetic evaluation set representing Hindi, English and code-switched speech.
- ABDM sandbox path and facility responsibilities confirmed.
- Clerk and hospital-SSO threat model approved, including outage and account-linking recovery.
- The mock-only provider decision, deterministic fallback and manual workflow are approved for engineering development.

## Phase 1 — Safe clinical workflow MVP

Duration target: 8–12 weeks.

### Build order

1. Repository tooling, Docker-based local environment, CI checks, secrets handling and contract generation.
2. Next.js application shells plus Clerk integration for patient, doctor and administration audiences.
3. FastAPI token verification, internal identity mapping, facility boundaries and RBAC/ABAC enforcement.
4. Internal patient identity, safe kiosk pre-auth and assisted registration.
5. PostgreSQL transactional schema, MongoDB artifact collections, object-store registry and cross-store reference rules.
6. Encounter and structured case-taking state machine with WebSocket progress updates.
7. Mock-only clinical task router with schema validation and deterministic manual fallback.
8. AI4Bharat/Bhashini ASR, patient confirmation and correction workflow.
9. Object upload, malware scanning and initial OCR routing with immutable source retention.
10. PyTorch clinical NLP and versioned deterministic Python red-flag rules.
11. Draft summary with provenance plus clinician correction, sign-off and immutable audit.
12. Kafka workers fed from a PostgreSQL transactional outbox for async document, summary and alert workflows.
13. Direct-to-quarantine object upload plus route-specific NGINX/gateway limits and timeout propagation.

### Defer

- Production approval/scaling of the implemented Elasticsearch derived-search
  slice, Kubernetes service mesh and multi-region deployment.
- Generative model serving and Drools-style rule authoring; neither is authorized by the current product scope.
- Autonomous diagnosis, prescription or AI-only emergency decisions.
- Full longitudinal reasoning across every available patient document.

### Exit gate

- A supervised consultation completes end-to-end.
- No AI draft enters the signed record without clinician approval.
- Critical symptom test cases meet the clinician-approved recall target.
- FastAPI rejects invalid issuer/audience/expired Clerk tokens and every tested cross-role access attempt.
- The platform remains usable for manual entry when the mock assistant or ASR is unavailable, subject to documented identity safeguards.
- Restore drill, access audit and incident runbook pass.

## Phase 2 — Hospital pilot and asynchronous processing

Duration target: 8–10 weeks.

### Work

- Harden Kafka recovery, idempotency, retry/dead-letter handling, PostgreSQL outbox re-dispatch and replay drills.
- Add OCR/document worker and source-linked extraction review.
- Add deterministic red-flag and workflow alert rules.
- Add patient-friendly summary and multilingual TTS.
- Add SMS reminders containing minimal sensitive information.
- Add offline capture with encrypted local queue and explicit sync state.
- Integrate ABDM sandbox identity/linking/consent flows.
- Add operational dashboards for latency, failures and AI quality.
- Add normalized mock results, bounded failure handling and approved manual-fallback UX.
- Design shared pilot deployment only after identity, data-service and owner approval gates pass.

### Exit gate

- Measurable reduction in doctor documentation time.
- Acceptable ASR and clinical-entity error rates by language and environment.
- Zero unresolved high-severity consent or cross-patient data leaks.
- Kafka outage recovery, duplicate delivery, replay and idempotency exercises pass.

## Phase 3 — Multi-facility scale

Duration target: 12–16 weeks after pilot evidence.

### Work

- Facility-aware data isolation and policy enforcement.
- ABDM production onboarding and HIP/HIU flows.
- HPR/HFR verification where applicable.
- HIS, LIMS and PACS adapters.
- Validate and scale the implemented reviewed-record Elasticsearch projection;
  separately design audit exploration and aggregate dashboards.
- Scale Kafka partitions from measured queue age and throughput without adding model-provider routing.
- Keep summary execution mock-only; a different provider requires explicit scope change and a new ADR.
- Autoscale non-model workers from measured queue depth and latency where justified.
- Add WhatsApp using explicit opt-in and approved low-PHI templates.
- Implement production disaster recovery and regional failover exercises.

### Exit gate

- Load, failover, privacy and clinical-safety targets pass at projected peak volume.
- Search rebuild/reconciliation is rehearsed at projected scale and summaries can
  be rebuilt from source systems.
- Kafka replay and idempotency exercises pass at projected peak scale.
- Facility onboarding is repeatable without code forks.

## Phase 4 — Validated advanced assistance

- Specialty-specific interviews.
- Care-gap suggestions and longitudinal risk signals.
- Retrieval-assisted clinical summaries with statement-level citations.
- De-identified analytics governed by explicit purpose and access controls.
- Any future model experiment only after an explicit product-scope change and new hazard analysis.

Every advanced feature requires a new hazard analysis, clinical evaluation and rollback plan.

## Cross-phase workstreams

| Workstream | Continuous outputs |
|---|---|
| Clinical safety | Hazard log, test cases, approval evidence, incident review |
| Security/privacy | Threat model, access reviews, key rotation, breach drills |
| Data | Migrations, quality rules, lineage, backup restoration |
| AI/ML | Model cards, evaluation reports, drift and cost monitoring |
| UX | Field research, accessibility tests, comprehension metrics |
| Reliability | SLOs, capacity plans, runbooks, recovery exercises |

## First backlog slices

| Slice | Demonstrable outcome | Dependencies |
|---|---|---|
| S1 | Clinician can securely sign in to a facility | IAM, authorization policy |
| S2 | Operator can register and safely find a patient | MPI, audit |
| S3 | Patient can complete one structured complaint flow | Encounter state machine, patient PWA |
| S4 | Doctor sees the confirmed transcript and unresolved questions | Conversation orchestration, clinician web |
| S5 | Doctor edits and signs a note | Clinical record, provenance, audit |
| S6 | Patient receives a simple approved summary | Signed note, multilingual renderer/TTS |
| S7 | [Uploaded prescription becomes a reviewed structured document](PHASE-7-DOCUMENT-INGESTION-OCR.md) | Object storage, scanning, OCR worker |
| S8 | ABHA-linked record flow works in sandbox | Consent service, ABDM adapter |
| S9 | Authorized staff search signed summaries/reviewed facts and patients see a self-scoped longitudinal view | Phase 8 signing, Phase 7 promotion, Elasticsearch, durable search audit |
