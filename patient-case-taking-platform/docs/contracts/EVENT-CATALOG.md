# Event Catalog

## Standard envelope

Every event contains:

- `event_id`
- `event_type`
- `event_version`
- `occurred_at`
- `producer`
- `tenant_or_facility_id`
- `correlation_id`
- `causation_id`
- `aggregate_type`
- `aggregate_id`
- `data_classification`
- `idempotency_key`
- `attempt`
- `artifact_refs`
- `payload`

Do not include raw audio, images, PDFs, unrestricted transcripts, prompts, completions, access tokens or secrets. Use opaque internal artifact IDs; consumers obtain short-lived authorized object access after authorization.

## Initial events

| Event | Producer | Primary consumers |
|---|---|---|
| `PatientRegistered.v1` | Clinical platform | Audit, integration projector |
| `ConsentChanged.v1` | Consent module | ABDM adapter, audit, access cache invalidator |
| `EncounterStarted.v1` | Encounter module | Conversation orchestrator, audit |
| `AnswerConfirmed.v1` | Encounter module | Summary worker, clinical safety evaluator |
| `DocumentUploaded.v1` | Document registry | Malware scanner |
| `DocumentUploadExpired.v1` | Upload cleanup worker | Operations/audit |
| `DocumentScanStarted.v1` | Malware scanner | Operations/audit |
| `DocumentScanCompleted.v1` | Malware scanner | Page normalizer, operations |
| `DocumentScanFailed.v1` | Malware scanner | Operations/manual-resolution queue |
| `DocumentNormalizationStarted.v1` | Page normalizer | Operations/audit |
| `DocumentPagesNormalized.v1` | Page normalizer | OCR worker |
| `DocumentNormalizationFailed.v1` | Page normalizer | Operations/manual-resolution queue |
| `ai.ocr.requested.v1` | OCR worker | Operations/audit |
| `ai.ocr.completed.v1` | OCR worker | Extraction worker |
| `DocumentOcrFailed.v1` | OCR worker | Retry scheduler/operations |
| `DocumentOcrDeadLettered.v1` | OCR worker | Manual-review/operations queue |
| `DocumentProcessingCompleted.v1` | Extraction worker | Clinical review queue |
| `DocumentExtractionFailed.v1` | Extraction worker | Retry scheduler/operations |
| `DocumentExtractionDeadLettered.v1` | Extraction worker | Manual-review/operations queue |
| `DocumentManualReviewRequested.v1` | Clinical document review | Clinical review queue/audit |
| `DocumentReviewDecisionRecorded.v1` | Clinical document review | Audit/clinical workflow |
| `DocumentReviewCompleted.v1` | Clinical document review | Reviewed-fact promotion worker |
| `ReviewedDocumentFactsPromoted.v1` | Reviewed-fact promotion worker | Timeline/FHIR/search consumers |
| `ReviewedDocumentFactsWithdrawn.v1` | Reviewed-fact promotion worker | Timeline/FHIR/search consumers |
| `ClinicalRecordChanged.v1` | Clinical record module | Summary worker, search projector, ABDM adapter |
| `clinical.summary.generated.v1` | Summary workflow | Audit/future projector |
| `clinical.summary.edited.v1` | Summary workflow | Audit/future projector |
| `clinical.summary.submitted.v1` | Summary workflow | Clinical review queue |
| `clinical.summary.rejected.v1` | Summary workflow | Audit/future projector |
| `clinical.summary.regenerated.v1` | Summary workflow | Audit/future projector |
| `clinical.summary.signed.v1` | Summary workflow | Clinical record projector |
| `CriticalAlertRaised.v1` | Alert worker | Clinical inbox, notification policy |
| `NotificationRequested.v1` | Owning workflow | Notification worker |
| `NotificationDeliveryUpdated.v1` | Notification worker | Owning workflow, operations |

## Event backbone

Kafka is the asynchronous backbone from MVP. PostgreSQL stores durable job state and the transactional outbox; Kafka provides transport, isolated consumer groups, bounded replay and dead-letter handling. Select a managed or self-operated Kafka deployment after residency, support, cost and operational review. No producer or consumer may depend on provider-specific behavior without an ADR.

## Topic plan

| Topic | Purpose | Transport retention |
|---|---|---|
| `ai.asr.requested.v1` | Submit asynchronous transcription jobs | 24 hours |
| `ai.asr.completed.v1` | Announce persisted transcript artifact | 7 days |
| `ai.ocr.requested.v1` | Submit document OCR jobs | 24 hours |
| `ai.ocr.completed.v1` | Announce persisted extraction artifact | 7 days |
| `clinical.summaries.v1` | Reference-only Phase 8 summary lifecycle events delivered by the leased transactional-outbox publisher | Retention pending privacy/volume/recovery approval |
| `clinical.triage.alert-raised.v1` | Announce deterministic red-flag escalation | 90 days, subject to volume and policy |
| `clinical.documents.v1` | Transport reference-only Phase 7 document lifecycle, review and promotion events | 30 days pending privacy/volume/recovery approval |
| `audit.event-recorded.v1` | Transport an audit projection event | 7–30 days; never the compliance archive |

Topic payloads contain metadata and artifact references only. Retention values are planning defaults and require privacy, volume and recovery validation.

## Consumer groups

- `asr-workers` consume ASR requests and publish completed artifact references.
- `ocr-workers` consume OCR requests and publish completed artifact references.
- Summary generation is synchronous through the offline mock provider. The
  `clinical_summary_outbox` transactionally records reference-only lifecycle
  events; Kafka publication is not yet implemented and is a documented Phase 8 gate.
- `triage-engine` evaluates confirmed structured facts and raises deterministic alerts; an LLM is never the sole red-flag detector.
- `document-pipeline-workers` scan, normalize, OCR and extract from durable
  references; they never consume raw files or OCR text from Kafka payloads.
- `document-promotion-workers` consume completed-review references and promote
  only accepted/corrected candidates into authoritative facts.
- `audit-projector` writes the immutable audit sink and a time-bounded Elasticsearch projection.

## Delivery rules

- Producers use a transactional outbox.
- The Phase 7 outbox publisher leases unpublished rows with `SKIP LOCKED`, uses
  the aggregate ID as the ordered Kafka key, retains the event ID in the
  envelope, applies bounded retry/backoff and records terminal dead-letter
  state. Publishing is at-least-once; consumers must remain idempotent.
- Consumers are idempotent using a PostgreSQL processed-event ledger and uniqueness constraints such as `(job_id, stage, model_version)`. Redis may accelerate the check but is not authoritative.
- Schemas are backward compatible within a major version.
- Retries use a maximum of three attempts with exponential backoff and full jitter. Kafka implementations use explicit retry topics or a delayed scheduler rather than blocking partitions.
- Messages that still fail move to a stage-specific dead-letter topic with error class, attempt count and a PHI-safe remediation reference.
- Bloom filters are not used for correctness-sensitive deduplication because false positives could suppress clinical work.
- Events are not used as an undocumented substitute for synchronous authorization checks.
- Each request carries deadline, priority, execution eligibility and estimated token class. Admission control bounds topic age/backlog; Kafka is not an unlimited overflow buffer.
