# Phase 8 summary workflow runbook

## Scope

This runbook covers the durable mock-only clinical summary workflow. It does not
authorize real-patient use. Use synthetic data until clinical, privacy/security,
accessibility, operations and facility approvals are recorded.

## Runtime invariants

- `LLM_PROVIDER` is exactly `mock`.
- `SUMMARY_WORKFLOW_ENABLED` is an explicit kill switch.
- No GPU, model artifact or hosted model credential is required.
- `clinical_summary_workflow` stores clinical content under forced tenant RLS.
- `clinical_summary_action` and `clinical_summary_outbox` contain metadata only.
- Signed rows and action rows are protected by database triggers.

## Enable and verify

Set `SUMMARY_WORKFLOW_ENABLED=true` and `LLM_PROVIDER=mock`, apply migrations and
restart the API. Verify `/readyz`, then use a synthetic doctor token to call
`PUT /api/v1/summary-workflows/contexts` and `POST
/api/v1/summary-workflows/generate`.

Expected behavior:

- another configured provider returns HTTP 503 without provider traffic;
- absent confirmed context returns 404;
- stale edits return 409;
- illegal state transitions return 422;
- cross-tenant reads return 404 and wrong-facility access returns 403;
- nurse-only forbidden actions return 403;
- fallback drafts report `provider=template-fallback` and `degraded=true`.

## Disable or degrade safely

Set `SUMMARY_WORKFLOW_ENABLED=false` and restart the API to stop new reads and
commands. Existing database records remain intact. Clinicians must use the
facility-approved manual documentation process; never bypass signing or remove
warning flags to work around an outage.

If the mock provider emits malformed output, the router automatically uses its
bounded template fallback. Investigate by error class and opaque IDs only. Do
not copy clinical narrative into tickets, chat, logs or metrics.

## Recovery checks

1. Confirm PostgreSQL health and migration 12 in `schema_migration`.
2. Confirm the caller has tenant/facility scope and an allowed clinical role.
3. Confirm the encounter has a clinician-confirmed context.
4. Check status, `lock_version`, provider and degraded state without exporting content.
5. Verify action/outbox counts match the workflow mutation count.
6. Check `summary-outbox-publisher` logs for retry/dead-letter error classes;
   event payloads must contain identifiers, status and version only.
7. Re-enable only after focused API and live repository tests pass.

Do not edit database rows manually. A signed-record correction requires a
future governed addendum workflow; it is not an incident workaround.

## Current operational gaps

- Downstream summary-event consumers and production alert thresholds are not implemented.
- Clerk/JWKS production identity and facility membership remain pending.
- Backup/restore, load, security and staged rollback drills are pending.
- No alert thresholds or production SLOs are approved.
