# Conceptual Data Model

This is a planning model, not a final migration. Names and constraints are refined through workflow discovery and FHIR/ABDM mapping.

## PostgreSQL regulated workflow entities

| Entity | Purpose | Important relationships/constraints |
|---|---|---|
| `tenant` | Hospital network boundary | Parent of facilities; all scoped rows carry `tenant_id` |
| `facility` | Hospital/site | Unique external identifiers per tenant |
| `department` | OPD or specialty | Belongs to facility |
| `patient_profile` | Internal patient identity/demographics | Non-semantic UUID; ABHA stored as verified external identifier, never primary key |
| `consent_artifact` | Notice, purpose, scope, expiry, delegation and revocation | Immutable versions; signed receipt reference in object storage |
| `intake_session` | Kiosk/PWA session and sync status | Expiring, facility-scoped, optionally pre-auth with no record-search authority |
| `encounter` | Case-taking/consultation lifecycle | Patient, facility, department and timestamps; explicit version for optimistic concurrency |
| `confirmed_answer` | Patient-confirmed structured response | Unique by encounter/question/version; source utterance reference |
| `triage_flag` | Deterministic risk signal and acknowledgement | Rule version, severity, evidence, owner and override reason |
| `provider_review` | Draft correction, approval and signature | Clinician identity, version and immutable signed output |
| `document_registry` | Metadata and processing status | Object ID, checksum, document class, encounter/patient association |
| `queue_token` | Facility flow token | Facility/day scoped uniqueness; no diagnosis in public display value |
| `ai_job` | Durable asynchronous workflow state | Unique idempotency key, stage, model version, artifact references and attempt state |
| `integration_event` | ABDM/HIS callback and reconciliation state | External correlation ID and replay-safe status |
| `audit_log` | Canonical audit control record | Append-only actor/action/purpose/target/outcome; immutable archive reference |

Recommended measured index candidates include `(facility_id, encounter_date)`, `(patient_id, created_at)`, `(tenant_id, status, updated_at)` for jobs and unique `(job_id, stage, model_version)` for AI results. Do not add or partition indexes without query-plan and cardinality evidence.

## MongoDB evolving artifacts

- transcript turns and multilingual utterance objects;
- OCR spans, layout/bounding boxes and extraction envelopes;
- versioned model prompts/results stored under approved minimum-necessary policy;
- evolving AYUSH assessment payloads;
- versioned summary drafts and confidence/provenance metadata.

Every artifact carries tenant, facility, patient/encounter where applicable, source object, model run, schema version and retention class. Clinician-approved facts are promoted into PostgreSQL; application reads do not infer signed truth from the latest MongoDB document.

## Object storage

Store immutable/checksummed raw audio, uploaded scans, normalized images/PDFs, OCR overlays, generated FHIR Bundles and signed consent receipts. Use separate upload quarantine, malware-scanned, clinical and archive prefixes/buckets with encryption, lifecycle and access controls.

## AYUSH extension

Keep an explicit versioned ontology for Dashavidha Pariksha, Prakriti/Vikriti, Agni, Koshtha, Ahara-Vihara, Nidana, Samprapti, intervention history and response. Store the evolving assessment envelope in MongoDB, but promote confirmed observations and the clinician-signed AYUSH summary into PostgreSQL with confidence and provenance. Map to standard FHIR resources where semantics fit and use governed India/local extensions only where needed.

## Multi-tenancy

- Every regulated row is scoped by `tenant_id` and `facility_id` where applicable; department adds a workflow scope, not a security substitute.
- Authorization applies tenant, facility, care relationship, purpose, consent and sensitivity filters at the API and database-access layers.
- Cross-tenant analytics use explicitly de-identified projections and separate privileges.
