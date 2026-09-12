# Alert Worker

The implemented prototype timer lives in `apps/api/app/rules/alert_timers.py`.
It owns escalation scheduling for durable alerts; canonical rules still run in
the API on confirmed patient evidence. No LLM controls escalation.

Start with an explicit facility policy using the optional `triage-timers` Compose
profile. Both `TRIAGE_WORKFLOW_ENABLED` and `ENABLE_DEMO_ROUTES` must be true.
`TRIAGE_TIMER_POLICY_FILE` selects a read-only JSON policy mount. The supplied
example is synthetic showcase configuration, not a clinical response standard.

Apply migration 0017 before running the timer. From `apps/api`, inspect and
explicitly activate the policy before starting workers:

```bash
python -m app.rules.alert_timers status --policy ../../services/alert-worker/policy.example.json
python -m app.rules.alert_timers activate --policy ../../services/alert-worker/policy.example.json --operator-id <operator-uuid> --expected-revision 0 --reason-code initial_activation
python -m app.rules.alert_timers forever --policy ../../services/alert-worker/policy.example.json
```

Each policy binds tenant, facility, worker actor, policy ID/version, owner reference
and one to five strictly increasing deadlines measured from original alert creation.
Each step escalates to the doctor role; later steps re-emit escalation if still
unacknowledged. Exhausted ladders remain visibly escalated and open for staff
action. They never auto-resolve. Policy changes require a new reviewed version;
the full content fingerprint separates histories and each step stores its snapshot.
Reapplying the identical policy does not re-run completed steps. A changed policy
applies to outstanding alerts using their original creation time, so operators
must assess overdue alerts before activating a replacement.
Activation/deactivation requires `DATABASE_MAINTENANCE_URL`, an operator UUID,
controlled reason and the current revision from `status`. These commands are
maintenance-only; a supplied operator UUID is an audit attribution, not workforce
identity verification. Production approval still requires a governed operator
identity boundary. Normal workers use `DATABASE_URL` and cannot activate themselves.

The registry permits only one active fingerprint per tenant/facility. Policy
artifacts and activation history are immutable. Reusing a policy ID/version with
different contents fails; stale activation revisions fail. Each timer transaction
holds a shared active-policy lock until its alert write commits. Replacement or
deactivation waits for earlier transactions and prevents later stale-policy writes.
Old workers become idle, even if they retain the old file. Stop those workers when
retiring a configuration to avoid unnecessary idle processes.

Use `deactivate` with the same operator/revision/reason arguments to pause centrally.
No clinical alert, escalation step or outbox event is deleted. Reactivating an
identical fingerprint resumes unfinished steps; it does not repeat completed ones.

The worker scans PostgreSQL with tenant scope and uses optimistic concurrency,
stable step idempotency keys and atomic lifecycle/history/outbox writes. It
recovers its progress after restart and skips acknowledged/terminal alerts.
Competing acknowledgements invalidate stale timer commands. Due-query filtering
excludes not-yet-due and completed ladders before the batch limit. Kafka outages
do not stop escalation persistence. Publication uses the separate alert outbox
worker, and publication does not mean staff acknowledged the alert.

Stopping the worker pauses future scheduling without deleting alerts, history or
queued events. Restart catches up overdue steps one per alert per scan. Migration
0017 adds the policy registry and audit history. CLI database failures exit visibly
so the supervisor restarts the process. Logs contain counts, not clinical text.
Production policy approval, operator governance and external delivery remain
separate release work; this runtime intentionally rejects production activation.
For rollback, deactivate/stop scheduling and retain the registry. The down migration
removes policy history and requires a deliberate archival/rollback procedure;
do not use it as an operational pause.
