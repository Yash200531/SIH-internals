# Phase 7 document-pipeline runbook

**Audience:** On-call engineering and facility operations  
**Scope:** Local/staging operational procedure; production commands require the
deployment platform's approved change process.

Never use destructive down migrations or delete source objects to recover the
pipeline. Preserve registry, outbox, source, OCR, review and fact history.

## Observe

```bash
docker compose ps -a
docker compose logs --tail 200 api document-scanner document-normalizer document-ocr-worker document-extraction-worker document-promotion-worker document-outbox-publisher
curl http://localhost:8000/healthz
curl -H "Authorization: Bearer $ADMIN_TOKEN" http://localhost:8000/api/v1/document-operations/status
```

The admin status endpoint is tenant-scoped and returns aggregate counts only:
review backlog/age, scan rejection, processing failure, OCR/extraction dead
letters, unpublished/dead-letter events and projection reconciliation issues.

## Stop automated interpretation while preserving upload and review

Set these values in `.env`:

```dotenv
DOCUMENT_OCR_AUTOMATION_ENABLED=false
DOCUMENT_EXTRACTION_AUTOMATION_ENABLED=false
```

Apply only the affected services:

```bash
docker compose up -d --build document-ocr-worker document-extraction-worker api
```

Confirm `/healthz` reports both switches as false. Upload, quarantine, scan,
normalization, source preview, existing review and reviewed facts remain
available. Documents with normalized pages can be moved to manual review:

```http
POST /api/v1/document-reviews/{document_id}/manual
Authorization: Bearer <nurse-or-doctor-token>
Idempotency-Key: <stable-operation-key>
Content-Type: application/json

{"expected_document_version": 9}
```

If no normalized page exists, the endpoint returns 422. Retry normalization or
recapture; do not create a source-unlinked clinical fact.

## Recover a dependency

1. Inspect the affected service logs and the tenant-scoped operations snapshot.
2. Restore the dependency without deleting volumes or artifacts.
3. Start/restart only the affected service.
4. Confirm backlog counts decrease and no dead-letter count increases.
5. Reconcile reviewed documents against promotion receipts and projections.
6. Record the incident, time window, event IDs and recovery evidence without PHI.

| Failure | Safe behavior | Recovery check |
| --- | --- | --- |
| Kafka unavailable | PostgreSQL outbox remains unpublished; publisher retries then dead-letters | Broker healthy; publisher running; unpublished count drains; replay uses original event/idempotency key |
| MongoDB unavailable | OCR/extraction draft is not reported complete; source/page persists | Mongo healthy; retry eligible run; immutable artifact exists before completion event |
| MinIO unavailable | Upload/preview/processing fails closed; acceptance requiring preview is blocked | Bucket private; exact object checksum matches registry; preview grants expire |
| ClamAV unavailable | Document stays quarantined and never reaches normalization | Scanner healthy/signature version recorded; re-run scan; state moves only on clean outcome |
| OCR/extraction repeated failure | Bounded attempts reach PHI-safe DLQ/processing failure | Open manual review when pages exist or rescan; document remains accessible to authorized staff |
| Promotion failure | Reviewed document remains reviewed; no draft facts are projected | Retry original completion event; one promotion receipt; projections match active authoritative facts |
| Projection mismatch | Authoritative facts remain unchanged | Run controlled rebuild; timeline/FHIR/search counts equal active fact set |

## Outbox dead letters

Do not edit event payloads or mint replacement clinical events. Diagnose the
transport/schema error, fix the publisher/consumer, then use an approved replay
operation that retains the original event ID and idempotency lineage. This
repository exposes the dead-letter state but does not yet ship an operator replay
command; escalation to engineering is required.

## Rollback

- Disable OCR/extraction automation first.
- Roll back by deploying the last approved application image or configuration.
- Keep additive migrations 0001–0011 applied; do not run destructive `.down.sql`
  files during an incident.
- Do not remove accepted facts. If a promoted document is entered in error, use
  the doctor-only audited withdrawal API, which preserves fact/status history and
  rebuilds disposable projections.
- Re-enable one facility/document class only after queue, DLQ, projection and
  source-preview checks pass.

## Production role requirement

Local Compose uses one PostgreSQL superuser for convenience. Production must
use separate service identities. Global queue workers require a narrowly scoped
maintenance role (or equivalent security-definer boundary) that can enumerate
tenant work and then sets tenant context for each transaction. The API role must
not receive `BYPASSRLS`; projection deletion is limited to rebuildable projection
tables. Role grants require privacy/security approval and negative isolation tests.
