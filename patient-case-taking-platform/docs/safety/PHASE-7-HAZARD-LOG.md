# Phase 7 document workflow hazard log

**Status:** Engineering candidate; owner review pending  
**Last reviewed:** 2026-09-04  
**Scope:** Prescription upload, malware scanning, normalization, OCR, extraction,
source-adjacent review and reviewed-fact promotion.

This log records safety controls implemented in the repository. It is not a
clinical-safety approval and must not be used to authorize real patient data.

| ID | Hazard | Principal cause | Implemented control | Verification | Residual action / owner |
| --- | --- | --- | --- | --- | --- |
| P7-H01 | Malicious or spoofed upload reaches processing | Browser MIME or filename trusted | Direct upload lands in private quarantine; finalize verifies stored length, SHA-256 and magic-byte MIME; ClamAV must return clean before promotion | Repository, MinIO and live ClamAV integration tests | Approve malware incident procedure and parser-abuse test pack — security/operations |
| P7-H02 | OCR/extraction is treated as clinical truth | Confidence or parser output bypasses review | OCR and extraction artifacts are immutable drafts; every candidate starts unreviewed; only accepted/corrected candidates are promotable | Review and promotion tests; live review-to-projection integration | Clinical-safety review of acceptance language and workflow |
| P7-H03 | Fact is accepted without source inspection | Preview outage or missing source geometry | Accept/correct/manual-entry require `source_verified`; preview failure returns 503; candidate carries page and region provenance | API/repository tests and source-link evaluation | Browser usability and source-highlight validation — accessibility/clinical safety |
| P7-H04 | Rejected or unresolved data appears in timeline | Projection reads draft tables or partial review finalizes | Finalize requires every candidate to be final; promotion query includes only accepted/corrected candidates; projections rebuild from active authoritative facts | Promotion/review tests and live integration | Independent data-lineage review — clinical platform owner |
| P7-H05 | Document statement is mistaken for a current medication | Projection overstates semantics | Facts are marked `document_statement=true` and `clinician_confirmed_current=false`; FHIR output is `Basic` tagged `document_stated` | Promotion contract tests | Approve downstream display wording — clinical-safety owner |
| P7-H06 | Automation failure loses the document or blocks care | Worker crash, OCR outage, extraction error | Source and page artifacts remain durable; retries are bounded; failed automation can enter manual review; OCR/extraction kill switches do not disable upload/review | Worker retry/DLQ and manual-fallback tests | Staging outage and recovery drill — operations |
| P7-H07 | Duplicate delivery creates duplicate facts | Worker retry or Kafka replay | Idempotency keys, deterministic draft/candidate IDs, promotion receipts and uniqueness constraints make processing replay-safe | Repository/outbox/promotion replay tests | Kafka replay drill — operations |
| P7-H08 | Cross-tenant or cross-facility disclosure | Global worker or reviewer uses wrong scope | PostgreSQL RLS is forced; request identity supplies tenant/facility scope; object preview is short-lived and exact-page scoped | Non-superuser RLS and authorization tests | Production role grants and object-policy review — privacy/security |
| P7-H09 | PHI leaks through events or operations | Raw OCR/value placed in Kafka/logs | Events contain opaque IDs/artifact refs and classifications; operations endpoint returns aggregate counts only | Event-payload assertions and operations tests | Log/telemetry sampling in staging — privacy/security |
| P7-H10 | Incorrect extraction performs well only on a tiny synthetic set | Dataset leakage or unsupported document class | Evaluation manifest is frozen, synthetic and provenance-labelled; lab reports and handwriting are excluded; thresholds remain null pending approval | Reproducible evaluation harness and candidate report | Approve representative datasets and thresholds before clinical rollout — clinical safety/facility |
| P7-H11 | Review history is overwritten or silently removed | Mutable audit/review rows | Review decisions are append-only; candidate/document updates use optimistic concurrency; withdrawal preserves facts and status history | Migration trigger and concurrency/withdrawal tests | Backup/restore validation — operations |
| P7-H12 | Outbox backlog is invisible or silently discarded | Broker outage or repeated publish failure | Leased publisher retries with bounded backoff, marks dead letters and exposes PHI-free backlog counters | Outbox and operations tests | Alert thresholds and paging integration — operations |

## Release position

The engineering controls above reduce risk but do not close the Phase 7 release
gate. Real-data processing stays prohibited until the approvals and external
evidence listed in [`../governance/PHASE-7-APPROVALS.md`](../governance/PHASE-7-APPROVALS.md)
are recorded.
