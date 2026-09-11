# Data Ownership and Storage Plan

## Sources of truth

| Data | Owner | Primary store | Derived copies |
|---|---|---|---|
| Patient identity | Clinical platform / identity module | PostgreSQL | Search-safe lookup projection |
| Consent and delegation | Consent module | PostgreSQL + immutable audit | ABDM reconciliation view |
| Encounter answers | Encounter module | PostgreSQL | Summary/search projection |
| Signed clinical record | Clinical record module | PostgreSQL | FHIR document, search index |
| Raw audio and documents | Document registry | Object storage | Transcript, OCR and thumbnails |
| Document metadata | Document registry | PostgreSQL | Elasticsearch projection |
| Confirmed transcript facts | Encounter module | PostgreSQL | Summary/search projection |
| Raw transcript segments | Conversation orchestrator | MongoDB | Confirmed facts promoted through FastAPI/PostgreSQL |
| OCR/layout and intermediate model JSON | Document/AI workers | MongoDB | Reviewed facts and search projection |
| AI job/workflow state | Owning workflow/worker | PostgreSQL | Operational metrics |
| Versioned AI result envelopes | Owning AI worker | MongoDB | Reviewed/accepted facts in PostgreSQL |
| Session/cache/limits | Owning service | Redis | None; safe to lose/recreate |
| Search and operational analytics | Search projector | Elasticsearch | Rebuilt from authoritative data |
| Audit evidence | Audit component | Append-only/WORM archive plus PostgreSQL control records | Time-bounded Elasticsearch security projection |

## Identity rules

- Generate a non-semantic internal patient UUID.
- Store ABHA number/address as verified external identifiers with status and timestamps.
- Permit care before ABHA creation or linking.
- Maintain merge and unmerge history; never destructively overwrite duplicate identities.
- Separate caregiver/delegate identity from the patient identity.

## Clinical provenance

Every normalized fact should link to its source:

`Clinical fact → encounter/document → source segment/page/utterance → extraction/model version → confirmation history`

## Retention and deletion

Retention periods must be approved by clinical, legal and facility governance. Implement legal hold, consent withdrawal effects, deletion/anonymization workflows and backup expiry as separate policies. Do not promise immediate physical deletion from immutable backups; document the actual lifecycle.

## Database choice

Use PostgreSQL plus JSONB for transactional clinical state and FHIR representations. Use MongoDB for append-oriented raw transcript segments, OCR/layout JSON and versioned intermediate AI outputs whose schemas evolve independently of signed clinical records.

Cross-store rules:

- PostgreSQL owns workflow state and stable artifact identifiers.
- MongoDB artifacts reference internal facility, patient, encounter, source-object and model-run IDs; they never carry authorization policy as truth.
- A transactional outbox/event consumer advances processing state idempotently; no distributed transaction is assumed.
- Confirmed or clinician-approved facts are written to PostgreSQL with provenance and are not reconstructed from the latest MongoDB document at read time.
- MongoDB receives the same encryption, residency, retention, backup, restore, access-control and audit treatment as other PHI stores.
- Use Elasticsearch as the single derived search product. Do not operate Elasticsearch and OpenSearch in parallel.
- Elasticsearch indexes are tenant/facility filtered, access-controlled, lifecycle-managed and disposable; deleting an index cannot delete the authoritative record.
- Kafka retention is transport retention, not the seven-year audit archive. Compliance retention is policy-driven in the immutable archive.

## PostgreSQL scale plan

- Put PgBouncer in front of application connections and validate transaction-pooling compatibility.
- Use the primary for writes, signing, consent/authorization and read-after-write paths. Use replicas only for latency-tolerant history and reporting.
- Begin with measured indexes such as `(facility_id, encounter_date)` and `(patient_id, created_at)`; validate each with production-shaped `EXPLAIN ANALYZE` tests.
- Partition high-volume encounter and audit tables only after size/query evidence. Prefer time-based or time-plus-hash schemes over a facility-only split that can create hot partitions.
- Cache only explicitly classified views. Consent, authorization and safety-critical medication/allergy reads require freshness checks and cannot silently use stale values.
