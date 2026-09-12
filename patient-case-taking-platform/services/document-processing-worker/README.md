# Document Processing Worker

The deployed document pipeline is implemented in `apps/api/app/documents` and
runs as separate Compose workers: scanner, normalizer, OCR, extraction and
outbox publisher. It processes immutable quarantine objects through ClamAV,
page normalization, PP-OCRv5 mobile recognition and deterministic prescription
extraction. PostgreSQL owns workflow state; protected MongoDB artifacts retain
OCR provenance, and MinIO stores source/page objects.

Extracted candidates remain unreviewed until an authorized clinician verifies
source evidence and finalizes review. Only reviewed, document-stated facts are
promoted into the patient timeline; they do not assert current medication use.

See [the Phase 7 plan](../../docs/plans/PHASE-7-DOCUMENT-INGESTION-OCR.md) and
[setup instructions](../../SETUP.md). From `apps/api`, run
`python -m tools.verify_document_pipeline` against the documented local demo
configuration to exercise a synthetic prescription through public APIs. This
creates synthetic records and explicit simulated review decisions; it must not
be used on clinical records. On Linux, pass `--font` with an installed TTF path.
