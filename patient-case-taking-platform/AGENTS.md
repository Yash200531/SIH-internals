# Repository Working Context

## Mission

Build a multilingual patient case-taking platform that reduces clinical documentation time while preserving informed consent, clinician control, provenance and patient comprehension.

## Non-negotiable boundaries

- Never treat AI output as a final diagnosis, prescription or signed medical record.
- Never use ABHA as the internal database primary key.
- Never place PHI, secrets or raw production records in prompts, fixtures, logs or event payloads.
- Never write directly to another service's tables.
- Never make Elasticsearch, Redis or a vector index the clinical source of truth.
- Never send raw audio or PDFs through Kafka; send encrypted object references.
- All critical alerts require deterministic rules, a documented clinical owner and an escalation path.

## Context loading order

Before changing a subsystem, read:

1. root `README.md` and `CONTEXT-GRAPH.md`;
2. the subsystem `README.md`;
3. relevant API/event contracts;
4. relevant architecture decision records;
5. clinical-safety and privacy requirements;
6. the matching test suites.

## Ownership rule

Each service owns its data and publishes changes using versioned contracts. Shared packages may contain schemas and policies, but not cross-service business logic.

## Definition of done

A change is incomplete until it has:

- tests proportional to clinical and privacy risk;
- audit and observability coverage;
- failure/retry behavior;
- migration and rollback notes where applicable;
- accessibility review for user-facing behavior;
- clinical-safety review when medical meaning can change.
