# Traffic control and clinical-assistance routing

## Current request path

```text
Client → edge/gateway → FastAPI → authorized workflow → offline mock provider
                                               ↘ deterministic template fallback
```

There is no model-selection surface, GPU/model server or hosted LLM route.
`LLM_PROVIDER=mock` is enforced by the Phase 8 dependency and provider factory.
A client cannot select a provider, and an unsupported configuration fails closed
without downloading artifacts or making network requests. ADR-008 owns this policy.

## Responsibility matrix

| Layer | Responsibilities | Must not do |
| --- | --- | --- |
| Edge/load balancer | DDoS controls, static assets, health-aware distribution and TLS | Cache authenticated clinical responses |
| Ingress | Request/body/header limits, throttles and route classes | Make clinical authorization decisions |
| API gateway | Token validation, request shaping, correlation and time budgets | Treat edge authentication as sufficient record authorization |
| FastAPI workflow | Tenant/facility/role checks, context assembly, schema validation, idempotency and state transitions | Accept client-supplied summary truth or bypass warning rules |
| Mock provider | Deterministic ontology questions and structured draft scaffolding | Diagnose, sign, use the network or choose another provider |
| PostgreSQL | Confirmed context, summary versions, append-only actions and transactional outbox | Store raw content in action/outbox metadata |

## Phase 8 admission and context policy

- Summary routes are off until `SUMMARY_WORKFLOW_ENABLED=true`.
- A nurse or doctor first confirms bounded encounter context.
- The generation command carries facility, patient and encounter identifiers,
  not chief complaint, answers or a provider/model name.
- The server recomputes Phase 6 warning flags and loads only active Phase 7
  reviewed facts under transaction-local tenant RLS.
- Inputs are bounded by Pydantic contracts; generations are schema validated.
- Idempotency keys are bound to a request hash. Reuse with different context is a conflict.
- Regeneration supersedes and creates linked versions in one transaction.

## Failure behavior

| Audience | Safe response |
| --- | --- |
| Patient | Continue with touch/manual intake and alert staff for visible urgent messaging. |
| Clinician | Show confirmed structured data and reviewed facts; use manual documentation when assistance fails. |
| Operations | Inspect opaque IDs, versions, status, provider, degraded state and error class only. |

Malformed mock output receives at most three attempts. The next result is a
deterministic template with `provider=template-fallback` and `degraded=true`.
No failure condition activates vLLM, HiMed, OpenAI, Claude or another provider.

## Events and traffic

Summary mutations write reference-only records to `clinical_summary_outbox` in
the same transaction as the workflow state. Its payload contains summary ID,
status, lock version and actor role—not clinical narrative. Kafka publication
for that outbox is not yet implemented and must not be represented as delivered.

Document upload and worker traffic follow the separate Phase 7 pipeline. Large
files upload to private quarantine and do not pass through the summary boundary.

## Verification checkpoint

- unsupported provider configuration returns 503;
- generation cannot accept/override narrative context;
- role, facility and tenant negative tests pass;
- deterministic flags survive provider output and edits;
- stale writes and changed-payload idempotency replays conflict;
- generate→edit→submit→sign and reject→regenerate paths pass;
- live PostgreSQL tests prove RLS, atomic regeneration and metadata-only outbox;
- manual/fallback behavior is documented in the Phase 8 runbook.
