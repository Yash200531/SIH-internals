# ADR-002: Define Authoritative and Flexible Data Stores

## Status

Accepted for planning.

## Decision

Use PostgreSQL as the transactional and clinical source of truth. Use MongoDB for versioned raw transcripts, OCR/layout JSON, intermediate extraction results and model-output envelopes whose schema evolves quickly. Use S3-compatible object storage for immutable audio and document binaries, Redis for ephemeral state, and Elasticsearch only for derived search and analytics.

MongoDB must not own patient identity, consent, authorization, encounter lifecycle, confirmed answers, signed notes, alert acknowledgement or audit evidence. PostgreSQL records the stable workflow/job reference for every MongoDB artifact, and MongoDB records are partitioned by facility/patient and governed by the same retention and access policies as other PHI.

## Consequences

- PostgreSQL remains the system of record for clinically actionable state and FHIR resources.
- MongoDB supports high-volume append-oriented transcript segments and heterogeneous OCR/model payloads without forcing them into the transactional schema.
- Cross-store transactions are forbidden; the transactional outbox and idempotent projectors reconcile references and processing states.
- Deleting or rebuilding a derived extraction cannot alter a signed clinical record.
- Elasticsearch text, analytics and vector indexes must be rebuildable.
- Operating MongoDB is an accepted cost; retention, backup, encryption, residency and restore testing are required before pilot use.
