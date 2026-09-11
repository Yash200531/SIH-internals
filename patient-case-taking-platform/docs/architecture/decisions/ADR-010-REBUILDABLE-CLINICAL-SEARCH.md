# ADR-010: Rebuildable, human-reviewed clinical search projection

## Status

Accepted for Phase 9 engineering implementation.

## Date

2026-09-05

## Context

MediKiosk needs longitudinal retrieval across signed summaries and reviewed
document facts. PostgreSQL already owns those records and enforces tenant RLS.
Elasticsearch is listed in the approved architecture for derived search, but no
search service or index currently exists.

The supplied Phase 9 completion report proposed indexing every patient record,
raw full text and resource family. That would let unreviewed OCR/model output
appear clinically authoritative and would claim canonical diagnoses, labs,
procedures and cross-provider identities that the repository does not own.

## Decision

Use Elasticsearch 9.3.0 as a disposable clinical-search projection while
PostgreSQL remains the only clinical source of truth.

- Index only clinician-signed summary content and active clinician-reviewed
  document facts.
- Never index raw OCR, transcripts, extraction candidates or unsigned summaries.
- Enforce tenant, patient and facility filters in every search query before
  relevance scoring.
- Synchronize from the existing PostgreSQL transactional outbox/Kafka events by
  re-reading the canonical row under tenant context.
- Provide a tenant-scoped full rebuild into a versioned backing index followed
  by an atomic alias swap.
- Store durable metadata-only search audit rows in PostgreSQL; do not retain raw
  query text in the audit trail.
- Support FHIR search only for resource mappings backed by these sources:
  signed-summary `DocumentReference` and reviewed-fact `Basic`.
- Keep vector, semantic-model and generative retrieval out of Phase 9.

The server and async Python client are pinned to the same 9.3.0 line for the
reproducible local baseline. Production security, topology and lifecycle policy
remain deployment decisions rather than being copied from local Compose.

## Alternatives considered

### PostgreSQL full-text search only

This would reduce local infrastructure and can remain an emergency fallback for
future evaluation. It does not exercise the approved rebuildable search-service
boundary, facets, highlights and alias-based recovery required by Phase 9.

### Index raw OCR and every summary version

Rejected because unreviewed or superseded text could be presented as a patient
fact. It also breaks the provenance and human-review invariants established in
Phases 7 and 8.

### Treat Elasticsearch as clinical truth

Rejected. Near-real-time indexing, replay and reindex operations are not an ACID
clinical record. Search loss must degrade retrieval without losing signed or
reviewed data.

### Implement every FHIR resource search immediately

Rejected until durable canonical stores and validated mappings exist. Returning
synthetic Condition, Observation or MedicationRequest resources would be a
false clinical assertion.

## Consequences

- Search may be temporarily stale or unavailable while direct record APIs remain
  functional.
- Event consumers and rebuild tooling must be idempotent and observable.
- Search authorization is defense in depth: API identity scope plus mandatory
  Elasticsearch filters.
- Adding another FHIR resource search requires a canonical source, mapping tests
  and an update to the Phase 9 contract.
- Performance and relevance claims must name the corpus and environment; they
  cannot be extrapolated from a small local benchmark.
