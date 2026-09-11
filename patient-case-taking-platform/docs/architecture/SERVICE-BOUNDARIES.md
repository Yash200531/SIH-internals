# Service Boundaries and Extraction Plan

Logical bounded contexts are not automatically separate processes. The MVP keeps transactional workflows together and isolates only workloads with distinct runtime or trust requirements.

| Logical context | MVP deployable | Owns | Scale extraction trigger |
|---|---|---|---|
| Identity and registration | `clinical-platform` | Internal patient/workforce mapping, duplicate and merge history | Dedicated MPI team, very high match traffic or stricter identity isolation |
| Consent and legal artifacts | `clinical-platform` | Consent lifecycle, delegation, receipts, revocation | Independent policy cadence or legally required isolation |
| Patient session and encounter | `clinical-platform` | Intake session, encounter state, confirmed answers | Never split before transaction boundaries are stable |
| Questionnaire/dialogue policy | `clinical-platform` + `conversation-runtime` | Ontology/state machine in core; streaming interaction in runtime | Independent streaming scale or dialogue team ownership |
| ASR/TTS gateway | `conversation-runtime` | Language/model routing, audio streaming, confidence/timing | Regional GPU/audio scale or provider isolation |
| Document ingestion and OCR/extraction | `ai-processing-workers` | Scan lifecycle and versioned AI artifacts | Separate CPU/GPU scaling or document-security zone |
| Clinical summarization | `ai-processing-workers` | Source-linked draft summaries | Independent GPU pool or model-release cadence |
| Triage/risk rules | `risk-and-notification-worker` | Versioned deterministic rules and alert lifecycle | Safety-team ownership or high-availability isolation |
| Notification/token routing | `risk-and-notification-worker` | Delivery policy, consent check, provider dedupe | Provider volume or blast-radius isolation |
| FHIR/ABDM integration | `integration-adapter` | External credentials, callbacks, reconciliation | Per-network adapters or separate compliance boundary |
| Audit/compliance | Canonical writes in `clinical-platform`; async immutable sink/projector | Audit evidence, export and searchable projection | Independent security operations ownership or extreme ingest volume |

## Boundary rules

- A context owns its schema and contracts even when it shares a deployable.
- In-process calls are preferred inside a deployable; versioned APIs/events cross deployables.
- No context writes another context's tables directly.
- Extract only after documenting ownership, migration, SLO, failure mode and rollback.
- Patient safety, consent and signing remain available without AI, search or the async broker.
