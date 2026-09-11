# Phase 8 summary workflow API

## Boundary

All routes are under `/api/v1/summary-workflows`, require a bearer identity and
enforce tenant, facility and clinical-role scope. `LLM_PROVIDER=mock` and
`SUMMARY_WORKFLOW_ENABLED=true` are required. Generation accepts identifiers
only; narrative is loaded from clinician-confirmed server context and unknown
fields are rejected.

## Lifecycle

| Method and route | Doctor | Nurse | Result |
|---|---:|---:|---|
| `PUT /contexts` | yes | yes | Create/update confirmed encounter context |
| `POST /generate` | yes | yes | Create idempotent unsigned draft |
| `GET ?encounter_id=…` and `GET /{id}` | yes | yes | Read authorized summaries |
| `PATCH /{id}/draft` | yes | no | Replace editable content with provenance |
| `POST /{id}/submit-review` | yes | yes | Move draft to review |
| `POST /{id}/reject` | yes | no | Record bounded reason |
| `POST /{id}/regenerate` | yes | no | Atomically supersede and create lineage version |
| `POST /{id}/sign` | yes | no | Lock reviewed content with integrity hash |
| `GET /{id}/history` | yes | yes | Read append-only action history |

Every mutation after creation carries `expected_version`. Generate and
regenerate require `Idempotency-Key`; reusing a key with different inputs
returns conflict. Deterministic warning flags cannot be removed. Signed rows
are immutable in both service rules and PostgreSQL triggers.

## Events and privacy

Each committed mutation writes a metadata-only event in the same PostgreSQL
transaction. `summary-outbox-publisher` leases pending rows and publishes to
`clinical.summaries.v1` with bounded exponential retry and dead-letter state.
The envelope contains identifiers, status, lock version and actor role—not
summary narrative, patient answers or document text.
