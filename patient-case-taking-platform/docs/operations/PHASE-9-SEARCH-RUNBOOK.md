# Phase 9 Clinical Search Runbook

## Scope and safety boundary

This runbook operates the derived Elasticsearch projection only. PostgreSQL is
the canonical source for doctor-signed summaries, active reviewed-document
facts and the durable search-access audit. Never repair search by editing
Elasticsearch documents manually, replaying raw OCR or enabling an unsigned
summary source.

The local commands use synthetic UUIDs. A shared environment additionally
requires an approved operator, change record, tenant scope and backup/rollback
procedure. The current repository has local engineering evidence only.

## Normal checks

```bash
docker compose ps postgres kafka elasticsearch search-index-worker
docker compose logs --since 10m search-index-worker
docker compose run --rm search-index-worker python -m app.search.worker reconcile-tenant --tenant-id <tenant-uuid>
```

A healthy reconciliation returns JSON with `"matches": true`, equal canonical
and indexed counts, and zero missing/unexpected IDs. Output contains identifiers
and counts only—never query text or clinical narrative. A mismatch exits non-zero.

## Elasticsearch unavailable

1. Confirm the Elasticsearch health state and worker error without retrying a
   clinician request in a loop.
2. Keep PostgreSQL, the API and canonical patient report/timeline routes running.
   Search may return 503; the patient UI retains its direct reviewed-record view.
3. Restore Elasticsearch using the environment's approved service procedure.
4. Wait for Kafka projection retries; offsets are committed only after a
   successful projection.
5. Reconcile affected tenants. Rebuild only tenants that still mismatch.

Do not route clinical queries to a broader tenant/facility scope as a fallback.

## Tenant reconciliation mismatch

1. Preserve the command output, correlation IDs and worker logs. Do not copy
   clinical narrative into an incident ticket.
2. Check PostgreSQL/Kafka/Elasticsearch availability and confirm the exact tenant.
3. Stop unrelated manual repairs; the event consumer is idempotent.
4. Run the tenant repair:

   ```bash
   docker compose run --rm search-index-worker python -m app.search.worker rebuild-tenant --tenant-id <tenant-uuid>
   ```

5. Require `"matches": true`. Run `reconcile-tenant` once more independently.
6. If the mismatch remains, stop and investigate the canonical projection or
   index mapping. Do not mark the incident recovered from equal counts alone;
   opaque ID sets must also match.

`rebuild-tenant` deletes/reloads only the requested tenant in the derived alias.
It does not modify PostgreSQL. The current local implementation does not claim a
zero-visibility-gap tenant repair at production scale; that remains a rollout
and recovery-drill gate.

## Disposable verification benchmark

```bash
docker compose run --rm search-index-worker python -m tools.verify_phase9_search --record-count 250 --iterations 5
```

The verifier uses a unique disposable alias, deterministic synthetic records and
one cross-tenant control. It checks four golden English/Hindi queries, records
client/server latency, reconciles IDs and deletes owned indices in `finally`.
It must report `"status": "PASS"`. The numbers are local engineering evidence,
not a capacity SLO or clinical relevance evaluation.

## Escalation and recovery gates

Escalate when any of these is true:

- a cross-tenant/patient/facility result appears;
- an unexpected record remains after repair;
- the durable audit write fails;
- Kafka repeatedly rewinds the same offset;
- canonical and indexed IDs cannot be reconciled;
- recovery would require swapping the shared alias from an incomplete corpus.

A production whole-index alias swap needs a complete canonical corpus, capacity
validation, a retained previous index and an approved rollback rehearsal. The
repository proves the alias primitive with tests and a disposable benchmark but
does not claim that production rehearsal is complete.
