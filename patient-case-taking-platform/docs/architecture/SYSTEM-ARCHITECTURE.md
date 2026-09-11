# System Architecture

## Architectural style

Use a microservice-light, domain-driven architecture: clear logical bounded contexts, but only a few deployables until scaling, security or team ownership requires extraction.

The core is a FastAPI application that initially owns patient identity, consent, encounters and signed records in one deployable application with strict internal module boundaries. This avoids premature distributed transactions while workflows are still changing.

The MVP deploys five coarse-grained units:

- `clinical-platform`: identity/registration, consent/legal artifacts, patient sessions, encounters, questionnaire state, signed records and canonical audit writes;
- `conversation-runtime`: WebSocket dialogue orchestration plus the ASR/TTS gateway;
- `ai-processing-workers`: document ingestion, OCR/extraction, clinical NLP, summaries and model jobs;
- `risk-and-notification-worker`: deterministic triage, alert lifecycle and token/SMS/WhatsApp routing;
- `integration-adapter`: FHIR/ABDM and hospital-system integration.

These deployables contain the logical bounded contexts defined in `SERVICE-BOUNDARIES.md`. Extract a context only when it has materially different scaling, security, availability or ownership needs, such as:

- conversation orchestration: streaming and session state;
- clinical assistance boundary: mock-provider schema enforcement and deterministic fallback;
- document worker: CPU/GPU-heavy asynchronous processing;
- summary and alert workers: event-triggered computation;
- notification worker: third-party delivery and retry isolation;
- ABDM adapter: external protocol, credentials and callback isolation.

## Edge request path

`Client → CDN/WAF/DDoS → managed load balancer → NGINX ingress → public API gateway → channel BFF/core API`

- CDN serves static public assets only.
- Authenticated clinical responses must use private/no-store caching rules.
- NGINX applies route-specific body/header limits, coarse throttles and ingress routing. Public TLS may terminate at the managed load balancer with re-encryption/mTLS to NGINX, or at NGINX for a single-site deployment.
- The public API gateway handles Clerk token validation, quotas, request shaping, timeout propagation, routing and correlation IDs. FastAPI still performs authoritative clinical authorization and database-backed idempotency.
- Rate limits differ for human interactive, file upload, integration callback and internal worker traffic.
- Large documents use authorized direct-to-quarantine object-storage uploads; they do not stream through NGINX/API pods except for a bounded fallback route.
- The internal AI model router is not the public API gateway. Clients cannot choose an arbitrary model/provider.

Detailed ownership, admission control and implementation slices are defined in `TRAFFIC-CONTROL-AND-MODEL-ROUTING.md`.

## Concrete technology choices

| Layer | Selected approach | Boundary |
|---|---|---|
| Web channels | Next.js/React TypeScript monorepo with PWA support | Separate patient, doctor and user-admin deployments share packages, not routes or feature state |
| API layer | FastAPI with Pydantic/OpenAPI | Modular clinical core plus independently scalable workers/adapters |
| Identity | Clerk for staff and patient web authentication; hospital SSO through supported OIDC/SAML integration | FastAPI verifies issuer, audience, signature and expiry, then applies internal facility/care/consent authorization |
| Realtime | WebSockets | Interactive transcript/status updates only; reconnect and authorization are explicit |
| Async jobs/events | Kafka from MVP with isolated consumer groups, retry topics and DLQs | PostgreSQL retains durable job state; Kafka is transport/replay, not clinical truth |
| Clinical dialogue/summary | Offline deterministic mock behind a versioned task router | No model downloads, GPU serving, hosted LLM API or client-selected provider; unsupported configuration fails closed |
| ASR/TTS | Existing ASR boundary plus deterministic mock TTS for current engineering | Confirm transcripts before use; mock TTS is a local WAV cue, while real speech providers remain gated |
| OCR | Real CPU PP-OCRv5 mobile worker; PaddleOCR-VL is an explicitly approved complex-layout option | Original documents remain immutable; every extraction retains page/region provenance and clinician review |
| Clinical NLP | PyTorch inference services | Versioned entity, negation, temporality and classification outputs |
| Rules | Versioned Python rules service first | Deterministic urgent-symptom and policy rules; consider Drools only for demonstrated authoring needs |
| Data | PostgreSQL + MongoDB + Redis + S3-compatible object storage + Elasticsearch 9.3 | Elasticsearch holds only rebuildable, human-reviewed search projections; PostgreSQL remains clinical truth |
| Runtime | Docker Compose for local engineering | Shared pilot/production topology requires separate operational approval |

## Authentication and authorization flow

1. Clerk authenticates staff or patient web sessions and issues a short-lived token for the correct application audience.
2. FastAPI validates the token against pinned Clerk JWKS metadata and maps `clerk_user_id` to an internal workforce, patient or caregiver identity.
3. The authorization layer evaluates role, facility, care relationship, consent, purpose and record sensitivity on every request.
4. Hospital SSO identities are linked to the same internal identity model; Clerk is replaceable at the adapter boundary.
5. Kiosk pre-auth may create only an opaque, expiring intake session. It cannot search records or display PHI until the patient or an attributed operator completes identity verification.

Patient record operations use the authenticated `/api/v1/patient-portal/me`
boundary. Tenant, internal patient ID and permitted facilities are derived from
the token. This boundary owns self-service consent, confirmed intake, upload
status, reviewed timeline and signed-report projections; it never exposes raw
OCR or an unsigned clinical summary. Local synthetic tokens are demo-only.

## Core modules

| Module | Owns | Does not own |
|---|---|---|
| Patient identity | Internal patient ID, demographics, duplicates, merges, external IDs | ABDM credentials or clinical notes |
| Consent | Purpose, scope, expiry, delegation, revocation, emergency access evidence | Authentication credentials |
| Encounter | Case-taking state, confirmed answers, encounter lifecycle | Model-provider logic |
| Clinical record | Signed notes, allergies, medications, observations, provenance | Search indexes |
| Document registry | Document metadata, patient/encounter association, processing status | Binary content |
| Audit | Actor, action, purpose, target, time and outcome | Ordinary application logs |
| Clinical search | Derived signed-summary/reviewed-fact documents, filters, facets and safe highlights | Raw OCR, unsigned drafts, authorization truth or canonical records |

## Clinical search and longitudinal boundary

Phase 9 adds a dedicated Kafka consumer for `clinical.summaries.v1` and
`clinical.documents.v1`. It accepts only summary-signed, reviewed-facts-promoted
and reviewed-facts-withdrawn events, re-reads PostgreSQL under tenant context,
then idempotently updates Elasticsearch. Kafka payloads are notifications, not
searchable clinical truth.

Every clinician query is constrained by token-derived tenant and facility scope
plus an explicit patient and treatment purpose. Patient access uses the
self-scoped `/patient-portal/me/longitudinal-timeline` route. Search, timeline,
FHIR search and CSV export write metadata-only rows to
`clinical_search_audit`; query text is stored only as SHA-256 and returned
narrative is never copied into audit rows. Nurses cannot export CSV.

The chronological timeline reads canonical PostgreSQL directly, so patient
signed reports and reviewed facts remain available when Elasticsearch is down.
Tenant repair replaces only that tenant's derived records and reconciles opaque
record IDs/counts. Whole-index versioned alias swaps are used only when the
complete canonical corpus is present.

## Conversation boundary

The conversation orchestrator is a deterministic workflow controller assisted
by the offline mock provider. Provider output cannot control authorization,
consent, emergency escalation or record signing.

Pipeline:

`audio → voice activity detection → language identification → ASR → normalization → clinical entity extraction → workflow decision → safety validation → response text → TTS`

In the current implementation the adaptive dialogue stage and TTS output are
deterministic mocks. TTS produces a bounded WAV acknowledgement cue rather than
intelligible clinical speech. This proves the request/playback/accessibility
contract without downloading a model or contacting a hosted provider.

WebSockets carry partial transcript and job-status updates. Durable workflow changes are written through FastAPI/PostgreSQL, then a transactional outbox publishes reference-only jobs to Kafka. Interactive audio is never routed through Kafka.

Each produced assertion stores:

- source utterance or document reference;
- speaker and capture time;
- provider/schema version;
- confidence;
- patient correction/confirmation;
- clinician correction/acceptance.

## Availability classes

| Capability | Target behavior |
|---|---|
| Registration and record view | Highly available; graceful degradation without AI |
| Clinician note/signing | Must remain available during queue/broker or mock-provider outage |
| Live transcription | Degrade to manual text entry |
| OCR and summary generation | Async, retryable, visible pending state |
| Notifications | Async, at-least-once with deduplication |
| Search | Derived search may return 503; canonical patient reports/timeline remain available |
| ABDM exchange | Async/callback-aware with reconciliation |

## Initial deployment

- Next.js applications and FastAPI services packaged as Docker images.
- Docker Compose for local development; Kubernetes for shared pilot and production environments.
- Managed PostgreSQL with encryption, point-in-time recovery and tested restore.
- Managed MongoDB or an equivalently operated replica set for raw transcript/OCR/model artifacts, with PHI-aware retention and restore tests.
- Versioned encrypted object storage with malware quarantine.
- Redis for ephemeral session/cache/rate-limit state only.
- Kafka provides the MVP asynchronous backbone. PostgreSQL owns job state and the transactional outbox; a Kafka outage must not lose an accepted clinical workflow.
- Redis is limited to cache, session, rate-limit and optional idempotency fast-path state; it is not the job or clinical source of truth.
- Elasticsearch 9.3 is implemented for scoped lexical search over signed
  summaries and active reviewed facts. Optional vector search, audit exploration
  and aggregate analytics remain unimplemented and require separate evaluation.
- No LLM/GPU service is part of the current deployment. CPU workers scale only
  where measured non-model workload requires it.
- Central OpenTelemetry-compatible metrics, logs and traces with PHI redaction.
- Secrets manager/KMS; no secrets in source or static environment files.
