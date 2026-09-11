# Phase 6 — Deterministic red-flag triage and alert lifecycle

**Status:** In progress; prototype only and not clinically validated

**Depends on:** Phase 5 pull request #7, authenticated tenant/actor context, durable PostgreSQL writes, and the transactional outbox

**Primary users:** patient, triage nurse, duty doctor, clinical-safety owner, and operator

### Implementation progress

- Slice 6.1 has started on `codex/phase-6-triage-plan`.
- The canonical prototype ruleset now owns Phase 5 warning detection and returns
  stable rule/ruleset versions, owner role, explanation code, and source paths.
- A bounded demo endpoint exposes evaluation metadata and states explicitly that
  no durable alert was created.
- Durable flags, authenticated ownership, acknowledgement, explicit doctor
  resolution, transactional history/outbox and fenced Kafka publication are
  implemented with local integration evidence recorded below.
- Assisted and touch patient confirmation now persist triggered flags before
  advancing. Prototype ruleset v2 / respiratory rule 1.0.1 recognizes the existing
  bilingual touch-choice labels; readable selected answers retain source paths.
- Governed staff handoff/override, policy timers, notification consumers,
  clinical approval and measured clinical validation remain incomplete gates.

### Slice 6.1 implementation record

| Delivered boundary | Repository evidence |
| --- | --- |
| Canonical evaluator | `apps/api/app/rules/triage.py` returns `flags_triggered` or `no_configured_flag` from the registered deterministic ruleset. |
| Versioned result | `RuleResult` carries rule version, ruleset version, explanation code, owner role, evidence paths and `prototype_only` approval status. |
| Phase 5 integration | The mock dialogue and summary provider imports the canonical evaluator; the duplicate warning-term table was removed from the LLM ontology. |
| Demo API | `POST /api/v1/triage/evaluate` accepts bounded controlled fields and reports explicitly that no durable alert was created. |
| Privacy boundary | Evaluation responses contain source paths rather than source text; audit metadata contains rule IDs, versions and outcome without symptom text. |
| Patient safety copy | Routine questioning stops on a configured critical match, while the patient view hides internal rule identifiers. |

Verified on commit `8c6f747`:

- `90 passed, 4 skipped` in the full API test suite;
- eight focused Phase 6 contract/regression tests;
- Ruff and mypy passed;
- patient kiosk lint and production build passed.

These checks establish prototype software behavior only. They do not establish
clinical sensitivity, specificity, approval, alert delivery, acknowledgement,
escalation performance or production readiness.

## 1. Outcome

Phase 6 will turn confirmed intake answers and verified vitals into versioned,
deterministic safety flags. A critical flag must interrupt routine patient
questioning, create one durable staff-owned alert, remain visible until it is
acknowledged or escalated, and retain an auditable explanation of the rule and
source facts that caused it.

This phase does not diagnose, assign a definitive clinical triage category, or
permit an LLM to create, lower, suppress, acknowledge, resolve, or override an
alert. Rule silence means **no configured deterministic flag matched**; it must
never be displayed as “routine” or “safe.”

## 2. Corrections to the supplied Phase 6 document

The supplied `PHASE-6-COMPLETE.md` is planning input, not implementation or
validation evidence. Before work starts, replace these claims with measured
evidence:

- The claimed `apps/api/src/services/triage_engine.py` and
  `packages/clinical-ontology/red_flags.json` do not exist in this repository.
- The API already contains `apps/api/app/rules/engine.py` and Python red-flag
  rules. Phase 6 will extend this boundary instead of creating a second engine.
- Sensitivity, specificity, latency, throughput, notification time, staff
  response time, “100+ real cases,” and clinician approval are unverified.
- SMS, audible alarms, acknowledgement, override approval, durable alerts, and
  queue bypass have not been implemented.
- “100% explainability,” “zero hallucination risk,” and “all criteria met” are
  not acceptable release evidence. Deterministic software can still contain
  incomplete rules, incorrect thresholds, language errors, and integration bugs.
- A seven-year immutable retention period is not assumed. Clinical, legal,
  privacy, and facility governance must approve each retention class and its
  deletion, legal-hold, backup-expiry, and access policy.
- Disease labels such as “heart attack” must not be inferred from symptom rules.
  User-facing copy states the observed warning pattern and required action.

## 3. Existing architecture to reuse

| Existing boundary | Phase 6 use |
| --- | --- |
| `apps/api/app/rules/engine.py` | Evolve the typed `RulesEngine`, `RuleResult`, and severity contract. |
| `apps/api/app/rules/red_flags.py` | Move starter rules into reviewed, versioned definitions without changing semantics silently. |
| `apps/api/app/llm/ontology.py` | Remove the duplicate Phase 5 warning-term authority; adapt dialogue interruption to the canonical rules engine. |
| `triage_flag` in `docs/architecture/DATA-MODEL.md` | Implement durable flag, ownership, acknowledgement, escalation, and override state in PostgreSQL. |
| `clinical.triage.alert-raised.v1` | Publish metadata-only alert events through the transactional outbox. |
| `risk-and-notification-worker` boundary | Own alert timers, escalation policy, delivery attempts, and notification status. |
| canonical audit emitter | Record PHI-minimized lifecycle metadata; the durable sink remains the authoritative audit path. |

Do not introduce a generic JSON rule DSL in this phase. Typed Python rules are
easier to review and test at the current scale. Reconsider a governed authoring
format only when non-developers must maintain enough rules to justify its parser,
schema, migration, and security burden.

## 4. Safety invariants

1. Evaluate only patient-confirmed answers, staff-verified observations, or
   device readings whose source and unit are explicit.
2. Preserve the source fact references, rule ID, rule version, ruleset version,
   evaluation time, and input version for every triggered flag.
3. A model output may request deterministic evaluation but cannot count as the
   sole fact that triggers a critical alert.
4. A lower-severity result cannot overwrite or hide an open higher-severity flag.
5. Re-evaluation is idempotent. The same encounter, input version, rule version,
   and evidence fingerprint creates at most one active flag.
6. Acknowledgement records receipt and ownership; it does not resolve the
   underlying clinical concern.
7. Override creates a new decision record with actor, reason code, free-text
   rationale, timestamp, original state, and approval when policy requires it.
   It never deletes the original flag.
8. Missing, malformed, stale, contradictory, or unit-ambiguous data must not be
   coerced into a reassuring result.
9. Critical patient messaging remains usable without Kafka, SMS, an LLM, or a
   notification provider. Staff delivery failures stay visible and escalate
   through a facility-approved fallback.
10. Events, logs, notification bodies, and metrics contain opaque IDs and rule
    metadata, not raw transcripts, symptoms, names, phone numbers, or ABHA values.

## 5. User requirements

### Patient

- Stop routine questions immediately after a critical configured rule matches.
- Present a short, bilingual, high-contrast, screen-reader-announced instruction
  to call nearby staff. Do not show diagnostic language or raw internal rule IDs.
- Keep a large manual “Call staff” action and an offline fallback instruction.
- Never claim the patient is safe when no rule matches.

### Nurse

- Show an ordered queue based on open deterministic flags and facility workflow,
  with source time, latest verified vitals, rule explanation, owner, and timer.
- Support explicit **acknowledge and take ownership**, handoff, add-note, and
  request-repeat-vitals actions.
- Keep delivery status and escalation state visible; do not treat a sent SMS as
  staff acknowledgement.

### Doctor

- Show the flag and its source evidence beside the editable clinical draft.
- Support accept-for-review, request clarification, resolve, and governed
  override workflows without converting a flag into a diagnosis.
- Signing a note and resolving an alert are separate audited decisions.

### Clinical-safety owner

- Approve rule intent, inclusion/exclusion criteria, wording, source references,
  test cases, severity, owner role, escalation policy, and rollback version.
- Review false-negative and false-positive cases by language and clinical group.

## 6. Canonical contracts

### Evaluation input

`TriageEvaluationRequest.v1` contains:

- tenant, facility, encounter, intake-session, and correlation IDs;
- monotonic encounter/input version and idempotency key;
- confirmed structured answers with question/ontology version and source refs;
- verified observations/vitals with value, unit, measured time, verifier/device,
  and quality state;
- language metadata used only by explicitly approved text-matching rules.

Raw audio, unrestricted transcripts, LLM prompts, and generated summaries are
not accepted as authoritative rule input.

### Rule definition

Every rule exposes:

- stable `rule_id`, semantic `rule_version`, and `ruleset_version`;
- clinical intent and non-diagnostic display message keys;
- severity and required owner role;
- typed evaluator over a documented input schema;
- evidence selectors and missing-data behavior;
- effective-from/retired-at state plus clinical approval reference;
- positive, negative, boundary, negation, stale-data, and unit test fixtures.

Activation is an allow-listed deployment/configuration decision. Editing a rule
creates a new version; it never mutates historical evaluation evidence.

### Durable triage flag

The PostgreSQL `triage_flag` aggregate contains at minimum:

- internal UUID, tenant/facility/encounter scope, and optimistic version;
- `rule_id`, rule/ruleset versions, severity, and PHI-safe explanation code;
- source artifact/field references and an evidence fingerprint;
- lifecycle state: `open`, `acknowledged`, `escalated`, `resolved`, or
  `overridden`;
- owner role/actor and acknowledgement, escalation, resolution timestamps;
- override reason/actor/approval reference when applicable;
- created/updated timestamps and the originating evaluation/input version.

Store lifecycle transitions as append-only history in addition to the current
projection. Enforce tenant/facility scope and legal transitions in the service
and database constraints.

### Events

Write flag state and the outbox row in one PostgreSQL transaction. Publish
reference-only, versioned events such as:

- `CriticalAlertRaised.v1`
- `CriticalAlertAcknowledged.v1`
- `CriticalAlertEscalated.v1`
- `CriticalAlertResolved.v1`
- `CriticalAlertOverridden.v1`
- `NotificationRequested.v1`
- `NotificationDeliveryUpdated.v1`

The repository event envelope, idempotency ledger, bounded retry, dead-letter,
and replay rules apply. Kafka transport retention is not the compliance archive.

## 7. End-to-end flow

1. Patient confirms an interpreted answer, or staff/device confirms a vital.
2. The clinical platform validates authorization, tenant/facility scope, input
   provenance, unit, freshness, and idempotency key.
3. The canonical rules engine evaluates synchronously before the next routine
   question is selected.
4. The API persists new/changed flags and outbox records transactionally.
5. A critical match returns immediate non-diagnostic patient guidance even if
   async infrastructure is unavailable.
6. The risk-and-notification worker consumes the outbox event idempotently,
   applies facility policy, assigns an owner, and requests allowed channels.
7. The nurse console receives the durable flag state. WebSocket updates improve
   immediacy but the PostgreSQL read model remains authoritative.
8. If no authorized staff member acknowledges within the facility-approved
   interval, the worker records and emits the next escalation step.
9. Acknowledge, handoff, resolve, and override commands use actor identity,
   optimistic concurrency, idempotency keys, and append-only audit evidence.

## 8. Delivery slices

### Slice 6.0 — clinical governance and frozen fixtures

- Name the clinical-safety owner and approving facility role.
- Agree on severity vocabulary, acknowledgement meaning, escalation ladder,
  allowed source types, freshness windows, and non-diagnostic copy.
- Start with a small clinician-authored starter set; do not copy the supplied
  list of 20+ conditions as if validated.
- Create synthetic/de-identified positive, negative, boundary, negated,
  temporally historical, Hindi, English, and code-switched fixtures.
- Record dataset provenance, reviewer, adjudication, and permitted use.

**Gate:** no rule can be enabled without an approval reference and frozen tests.

### Slice 6.1 — one canonical deterministic evaluator

- Extend `RuleResult` with version, explanation code, evidence selectors,
  severity, acknowledgement requirement, and owner role.
- Add typed normalization for structured facts, numeric units, freshness, and
  missing/conflicting data. Avoid free-text matching where structured facts exist.
- Route Phase 5 dialogue interruption through this engine and delete the duplicate
  warning-term authority only after equivalence/regression tests pass.
- Expose a demo-gated evaluation endpoint for contract tests; production callers
  use authenticated service context rather than body-supplied tenant IDs.

**Gate:** deterministic snapshot tests, property/boundary tests, and Phase 5
emergency-interruption regression tests pass.

### Slice 6.2 — durable flag and command model

- Add migrations, repositories, transition service, uniqueness constraints, and
  append-only lifecycle history for `triage_flag`.
- Implement authenticated list/detail, acknowledge, handoff, resolve, and
  override commands with role/purpose/facility authorization.
- Persist canonical audit and outbox records in the same transaction.

**Gate:** concurrent acknowledgement, retry/idempotency, cross-tenant denial,
illegal-transition, and audit-content tests pass.

### Slice 6.3 — outbox, worker, and escalation policy

- Implement outbox dispatch, processed-event ledger, bounded retry, dead-letter,
  and replay tooling using the existing event contracts.
- Add facility-owned escalation policy with explicit owner roles and intervals.
- Implement in-app delivery first. Add SMS/other providers only after consent,
  minimum-content, quiet-hours, residency, security, and failure-mode review.
- Record requested, attempted, delivered, failed, and acknowledged as distinct
  states.

**Gate:** broker outage, duplicate event, worker crash, provider timeout, stale
timer, and replay tests prove that an accepted flag is neither lost nor duplicated.

### Slice 6.4 — patient, nurse, and doctor experiences

- Connect the patient emergency state to canonical evaluation and preserve the
  accessible manual fallback.
- Replace the synthetic nurse alert cards with the durable work queue, ownership,
  acknowledgement, handoff, delivery, and escalation states.
- Add evidence-adjacent doctor resolution/override controls while keeping note
  signing separate.
- Test keyboard, screen reader, large text, high contrast, Hindi/English copy,
  poor connectivity, stale data, and concurrent staff updates.

**Gate:** usability and accessibility evidence exists for every safety-critical
state and failure path.

### Slice 6.5 — validation, observability, and controlled rollout

- Run the frozen offline suite and a separately governed prospective/shadow
  evaluation. Do not enter real cases into development environments.
- Measure critical-symptom recall, false-alert rate, negation/temporality errors,
  missing-data behavior, language/cohort slices, end-to-end alert persistence,
  delivery, acknowledgement, and escalation.
- Emit PHI-free metrics for rule version, result class, latency, outbox age,
  delivery status, open/unowned alerts, acknowledgement time, overrides, and DLQ.
- Canary one approved ruleset/facility at a time with a kill switch that returns
  to manual facility escalation without hiding existing alerts.

**Gate:** clinical-safety, privacy/security, accessibility, operations, and
facility owners sign the release evidence and rollback drill.

## 9. Verification matrix

| Area | Required evidence |
| --- | --- |
| Rule correctness | Positive/negative/boundary/negation/temporality/unit/stale/conflicting-data tests per rule and version. |
| API and authorization | Tenant/facility isolation, purpose/role checks, invalid provenance, idempotency, optimistic concurrency, and illegal transitions. |
| Safety workflow | Routine-question interruption, no-match wording, acknowledgement vs resolution, owner handoff, escalation timer, and higher-severity preservation. |
| Events | Transaction rollback, outbox recovery, duplicate consumption, retry/DLQ/replay, schema compatibility, and PHI-content scanner. |
| Notifications | Minimum-content templates, consent/policy checks, provider failure, alternate channel, and delivery-not-equal-acknowledgement. |
| UI/accessibility | Screen reader, focus transfer, keyboard/touch targets, contrast, zoom, bilingual comprehension, offline/degraded states, and stale timestamps. |
| Performance | In-process evaluator and end-to-end persistence/load tests with dataset size, hardware, concurrency, percentile, and error budget recorded. |
| Clinical validation | Approved protocol, dataset provenance, adjudication method, confidence intervals, subgroup results, failures, and signed decision. |

Tests use synthetic or appropriately governed de-identified fixtures. Any use of
real patient data requires separate authority, data-minimization, access control,
retention, and ethics/governance approval.

## 10. Metrics: targets are not achievements

| Signal | Initial planning position |
| --- | --- |
| Critical-symptom recall | Threshold set and signed by the clinical-safety owner after the validation protocol is approved; report confidence intervals and subgroup results. |
| False-alert rate/specificity | Measure per rule, facility, language, and source quality; approve an operational tolerance rather than assuming 80%. |
| Evaluation latency | Initial engineering objective: p95 under 100 ms in-process on recorded reference hardware; benchmark before claiming. |
| Alert durability | 100% of accepted flag transactions have a matching outbox record; verify by reconciliation tests and monitoring. |
| Time to staff-visible state | Define per facility and measure from durable flag creation, not from browser rendering alone. |
| Acknowledgement/escalation | Measure separately by severity, shift, owner role, delivery path, and facility; intervals are facility-approved policy. |
| Duplicate/lost alerts | Zero tolerated by invariant; verify with uniqueness, reconciliation, failure injection, and incident monitoring. |
| Override rate | Monitor by rule/version/actor role and review outliers; an override is not automatically a false positive. |

No metric is marked achieved until a reproducible report records the commit,
ruleset, dataset, environment, method, sample size, result, reviewer, and date.

## 11. Exit criteria

Phase 6 may be called complete only when all of the following evidence is present:

- one canonical, versioned deterministic engine drives patient interruption and
  durable clinical flags;
- every enabled rule has clinical ownership, approval reference, source schema,
  frozen fixtures, measured validation results, and rollback version;
- durable flag lifecycle, assignment, acknowledgement, handoff, escalation,
  resolution, override, audit, and outbox paths are implemented and tested;
- nurse and doctor views use authoritative data rather than synthetic alert state;
- patient critical messaging passes bilingual accessibility/usability review;
- authentication and tenant/facility authorization are enforced server-side;
- Kafka/worker/provider failures cannot lose an accepted flag and have a tested
  staff-visible degraded path;
- PHI scanners confirm events, logs, metrics, and notification templates contain
  no prohibited content;
- performance and clinical-validation reports contain reproducible measured data,
  including limitations and failures;
- retention and notification policies are approved rather than inferred;
- rollback, replay, reconciliation, and incident runbooks pass a staging drill;
- clinical safety, facility operations, privacy/security, accessibility, and
  engineering owners record approval.

Until then, repository and review documents must say **proposed**, **in progress**,
or **prototype only**—never “clinically validated,” “all targets met,” or
“production ready.”

## 12. Suggested pull-request sequence

1. `docs(phase6): approve contracts, hazards, and validation protocol`
2. `refactor(rules): establish canonical versioned triage evaluator`
3. `feat(triage): persist flags and audited lifecycle commands`
4. `feat(events): add outbox-backed alert and escalation worker`
5. `feat(ui): connect patient interruption and staff alert ownership`
6. `test(phase6): publish resilience, accessibility, and validation evidence`

Keep each PR deployable behind a deny-by-default facility/ruleset feature flag.
The flag may disable new evaluation or notification behavior, but it must never
hide flags already accepted into the durable workflow.

### Slice 6.2 continuation — 8 September 2026

Implemented `apps/api/app/rules/alert_lifecycle.py`, the immutable transition
boundary for acknowledge, handoff, policy-worker escalation, resolve and override.
It enforces tenant/facility/role, optimistic version and transition time; separates
receipt from disposition; requires verified handoff identity and recipient
acknowledgement; prevents stale acknowledgement timers from escalating an
acknowledged concern; and requires an owning doctor plus reason/protected rationale
for disposition and an approval reference for override.

Ten focused tests pass and mypy passes. This module is not yet wired to a public
endpoint or durable repository. An approval reference is required input here;
its authenticity must be checked by the future governance adapter. Do not claim
live alert delivery, approved rules, persistence or completed Slice 6.2 from
these pure transition tests. Atomic PostgreSQL projection/history/outbox storage,
authenticated input sourcing and staff UI remain the next implementation work.

### Durable alert repository — 8 September 2026

Migration 0015 adds `triage_flag`, append-only `triage_flag_history` and
`triage_outbox`, each with forced tenant RLS. The repository deduplicates raised
flags by encounter/input/rule/evidence version, serializes commands with a row
lock, checks expected versions, and replays matching idempotency keys. Current
state, protected history and metadata-only outbox rows commit or roll back together.

Live PostgreSQL tests pass for concurrent raise/acknowledgement, replay/conflict,
facility and tenant denial, RLS without superuser bypass, append-only history,
and rollback after a simulated transaction failure. Migration applies once in
an isolated schema and the second run applies zero changes. Full API regression:
421 passed, 28 skipped; Ruff and mypy (182 source files) pass.

This persistence layer is not yet connected to confirmed-intake evaluation or
public staff commands. Outbox transport, facility escalation policy, verified
workforce/approval adapters and UI remain open. Do not claim delivery from the
presence of an outbox row. Migration tested in disposable schemas only; apply
through the existing migration runner when enabling the workflow. Rollback must
export/retain alert history before using 0015's down migration; ordinary rollback
should disable new alert commands and retain data.

### Staff API and queue integration — 8 September

The authenticated API and staff queue now consume the durable repository. Staff
can explicitly review a consented accepted intake and evaluate its stored source
fields, then acknowledge/take ownership and resolve as owning doctor. The Alerts
page reads PostgreSQL through treatment-scoped APIs and retains a closed-state
view. Prototype rule creation remains demo-gated. See
[ALERT-API.md](../contracts/ALERT-API.md) for exact contracts and open boundaries.

Patient interruption-time alert creation, timed escalation/outbox publication,
verified workforce handoff, governance-approved override and a full authenticated
browser walkthrough remain open. Source/API/database integration tests do not
prove those missing paths or clinical approval.

### Alert outbox publication — 8 September

Migration 0016 and the optional `triage-outbox-publisher` Compose service now
publish reference-only alert envelopes to Kafka. Events retain stable identity,
serialize by alert version and use leased claims with UUID fencing. Broker outage
retries are bounded; exhausted events remain in dead-letter state and block later
alert events until maintenance replay. Queue delivery status is distinct from
staff acknowledgement. Five live database tests plus a separate real Kafka
receipt test pass. Operator replay currently requires maintenance access and
recording in the operations log; governed replay audit remains open.

Consumer notification workflow, facility-approved timers, patient interruption
persistence and governed staff handoff/override are still incomplete. A broker
receipt is not proof that any clinician has seen or responded to an alert.

### Patient interruption and policy registry — 9 September

Assisted and touch intake persist triggered flags before advancing questions;
both paths were verified in the browser with synthetic inputs. Timed escalation
uses an explicit facility ladder, immutable policy snapshots, stable step keys
and the existing transactional history/outbox. Migration 0017 adds a single
active policy per facility, immutable policy versions and activation history.
Expected activation revisions prevent lost updates; shared policy locks fence
old workers through alert commit when a policy is replaced/deactivated.

Maintenance CLI activation records an operator attribution and reason. Production
operator identity verification and clinical approval remain open; the runtime is
still prototype-only and demo-gated. No timer resolves alerts or treats broker
publication as staff acknowledgement. See services/alert-worker/README.md for
activation, pause, replacement and recovery procedures.
