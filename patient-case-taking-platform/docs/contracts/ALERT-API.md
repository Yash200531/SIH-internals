# Durable prototype alert API

All paths use `/api/v1/alerts`, clinician Bearer identity, token-derived
facility/tenant scope and explicit `purpose=treatment`. Responses are private,
no-store. Enable `TRIAGE_WORKFLOW_ENABLED` after migration 0015.

- `GET /` lists open/acknowledged/escalated alerts, severity first and then age;
  `limit` is bounded to 1–200 and `include_closed=true` includes historical states.
- `POST /from-intake/{id}` requires `{ "reviewed": true }`. The server loads a
  consented accepted intake, evaluates canonical rules over persisted confirmed
  source values and deduplicates immutable intake/rule/evidence versions. Extra
  caller-supplied source fields are rejected. Prototype evaluation additionally
  requires demo mode; disabling it does not hide previously persisted alerts.
- `POST /{id}/commands` accepts `action=acknowledge|resolve`, `expected_version`,
  and for resolution a controlled `reason_code` and protected `rationale`.
  `Idempotency-Key` is required. The owning doctor must resolve explicitly.
  This neither signs a note nor edits the original rule evidence.

Command errors: 404 inaccessible flag; 409 stale state or changed idempotent
request; 403 wrong role/owner; 422 malformed or illegal command. Retrying a
matching command returns its recorded result. Handoff, override and escalation
are not public commands. The prototype facility timer performs escalation through
the scoped repository using a versioned policy and persisted step identity.

Outbox rows are transactional intent, not proof of notification. The response
states `staff_notification_sent=false`. Consumer notification and verified
production operator identity/clinical approval remain separate incomplete work.

Migration 0017 adds immutable policy artifacts, a facility active-policy revision
and append-only activation history. Maintenance activation uses expected revisions.
Escalation transactions require the active fingerprint and bound worker actor,
holding a shared policy lock through commit. Deactivation/replacement therefore
fences old workers. This is not a public patient or staff command.

## Outbox delivery status

Alert list results include `delivery=pending|failed|broker_published`. The status
summarizes all events for that alert; a failed predecessor blocks later events.
The optional triage outbox worker publishes metadata envelopes to Kafka with
stable event IDs, lease fencing, bounded retry and maintenance-only replay.
Consumers must deduplicate event IDs. This does not implement external messages,
staff acknowledgement. Scheduling uses the separate facility timer worker.

## Patient-confirmed safety input

`POST /api/v1/patient-portal/me/safety-confirmations` uses verified patient Bearer
identity and requires both `TRIAGE_WORKFLOW_ENABLED` and `ENABLE_DEMO_ROUTES`.
The strict body contains `facility_id`, `encounter_id`, `consent_id`, positive
`input_version`, `confirmed: true`, `chief_complaint` (at most 500 characters),
and bounded ontology-keyed `confirmed_answers`. Patient and tenant IDs come
from the token. An active matching treatment consent is required.

The server evaluates canonical prototype rules without an LLM and atomically
saves all triggered flags, protected confirmed source evidence, history and
outbox intent. Identical input/rule versions deduplicate. A shared consent lock
serializes persistence with revocation; a revoked consent rejects even a replay.
Raw answers stay out of transport envelopes. Responses are private/no-store and
include `interrupt_required`, `durable_alert_count`, `staff_acknowledged: false`
and `approval_status: prototype_only`. No match is not a safety clearance.

Assisted and touch intake call this endpoint before advancing each question. A
trigger pauses questions and asks the patient to call nearby staff. A failed
check prevents the next AI request and displays a manual assistance message.
Saving a warning does not mean staff received or acknowledged it. Touch answers
use the selected option's visible label in the patient's language; free speech
is preserved. Respiratory rule 1.0.1 / prototype ruleset v2 recognizes the English
option label “Breathing Difficulty” and its Hindi equivalent. Governed production
rule approval remains separate work.
