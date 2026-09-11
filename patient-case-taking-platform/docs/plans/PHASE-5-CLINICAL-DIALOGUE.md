# Phase 5 — Clinical dialogue and draft summaries

## Current implementation boundary

Phase 5 currently uses an **offline deterministic mock provider**. It does not
load HiMed 8B, start vLLM, call an external API, or send patient content over the
network. This is the correct provider for contract development and supervised
workflow demonstrations while clinical model evaluation remains incomplete.

The task-level flow is:

`Patient/clinician UI → FastAPI clinical-ai route → LLMRouter → mock provider → Pydantic validation → PHI-minimized audit metadata`

The provider can be replaced later through the same interface, but changing
`LLM_PROVIDER` to anything except `mock` currently fails closed at startup/use.

## Delivered

- Hindi and English SOCRATES question sequencing.
- Deterministic warning-symptom detection that interrupts ordinary questioning.
- Draft clinical summary assembled only from confirmed structured facts.
- Versioned request/response schemas validated with Pydantic.
- At most three validation attempts followed by a touch/manual template fallback.
- Provider, task, schema version, and degraded status audit metadata without
  prompt, transcript, answer, or generated clinical content.
- Provider health contract explicitly reporting that external networking is not used.
- Bounded field lengths and clinician-review-required summary output.
- Technical confidence metadata whose schema explicitly states that it is not a
  clinical probability.
- Evidence pointers from generated fields to structured patient-response,
  document, or deterministic-rule paths without copying PHI into audit metadata.
- Patient assisted-question route connected to the mock dialogue and summary endpoints.
- Confirmed voice transcripts feed the returned SOCRATES domain before the next question.
- Polite assistant status, assertive bilingual emergency messaging, and a touch fallback.
- Editable patient review plus clinician edit, reject, and sign demonstration states.
- Phase 6 Slice 6.1 now supplies the single prototype warning-rule authority.
  Dialogue and summary responses use stable rule IDs from
  `phase6.prototype.v1`; patient emergency copy does not expose those internal IDs.

AYUSH Dashavidha remains represented in the existing structured AYUSH contract.
It is not inferred by the mock provider; a clinician or supervised workflow must
enter and confirm it.

## Run locally

Copy `.env.example` to `.env`, set `ENABLE_DEMO_ROUTES=true` and keep
`LLM_PROVIDER=mock`, then run `docker compose up --build`. No vLLM service,
model download, GPU, or external model credential is required. Open
`http://localhost:3000/case-taking/assisted`. The development-only endpoints are:

- `GET /api/v1/clinical-ai/health`
- `POST /api/v1/clinical-ai/dialogue/next`
- `POST /api/v1/clinical-ai/summaries/generate`

## Not complete / production release gates

- Clerk-authenticated actor and tenant context must replace body-supplied tenant IDs.
- Audit events must be written through the transactional outbox to durable storage.
- Deterministic red-flag rules require clinician approval, sensitivity testing,
  versioning, and linkage to the alert workflow.
- Draft acceptance/rejection and assistant sessions require authenticated durable persistence.
- Hindi, English, and code-switched scripts need usability testing with consented
  hospital samples.
- Any generative provider, including HiMed/vLLM, requires a separate approval for
  licensing, privacy, provenance, hallucination/omission, red-flag recall, latency,
  capacity, and rollback. It is deliberately not enabled in this phase.

## Safety gate status

| Requirement | Current status | Evidence / remaining work |
| --- | --- | --- |
| No autonomous diagnosis | Implemented in mock contract | Output schemas contain questions and draft facts, not diagnosis fields. |
| No treatment recommendations | Implemented in mock contract | No treatment or prescription output exists. |
| Emergency escalation | Partial | The canonical Phase 6 prototype ruleset interrupts dialogue and the patient UI presents an assertive bilingual staff-escalation message without exposing internal rule IDs; durable alert persistence, Kafka delivery, staff acknowledgement, and paging escalation are not implemented. |
| Uncertainty signal | Implemented with qualification | Every output has a technical confidence/completeness signal explicitly marked as not being a clinical probability. |
| Evidence linking | Implemented in API contract and demo UI | Outputs point to source field paths; the clinician view demonstrates source-adjacent editing, but durable evidence retrieval is not implemented. |
| Audit trail | Partial | PHI-minimized metadata is emitted in memory. Durable append-only storage, access controls, deletion jobs, and verified retention are release gates. |
| Human oversight | Partial | Summary output requires clinician review and the UI supports edit/reject/sign states; these decisions are browser-only demonstrations and are not durably persisted. |
| Prompt injection resistance | Implemented for mock boundary | The mock executes no prompt or code, users cannot select a provider/system instruction, inputs are typed and bounded, and outputs are schema validated. Future generative providers require a separate threat model. |

## Privacy and DPDP position

Do not label this implementation “DPDP compliant.” Compliance is an organisational
and legal conclusion that cannot be established by these API controls alone. The
mock provider keeps processing local and makes no provider API call, which removes
the external-model transfer path for this phase.

Full prompt/response logging is intentionally prohibited by default because it
would duplicate sensitive clinical content. The normal audit record contains task,
provider, schema version, resource identifier, outcome, and degraded status. If a
separate diagnostic trace is later approved, it must be redacted, access-controlled,
purpose-specific, consent/lawful-basis reviewed, encrypted, and deleted by a tested
retention job—not merely assigned a documented “30 days” value.

The DPDP Act requires consent to be specific, informed, unambiguous, and limited to
data necessary for the specified purpose. The final 2025 Rules also require a clear,
independent notice with itemised data and specified purposes. Therefore, “included
in general consent” is not accepted as sufficient design evidence for optional AI
processing. See the official [DPDP Act 2023](https://www.meity.gov.in/static/uploads/2024/02/Digital-Personal-Data-Protection-Act-2023-1.pdf)
and [DPDP Rules 2025](https://www.meity.gov.in/static/uploads/2025/11/53450e6e5dc0bfa85ebd78686cadad39.pdf).
