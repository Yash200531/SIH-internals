# ADR-007: Use Tiered Inference Behind One Router

## Status

Superseded by ADR-008. External generative providers and local LLM downloads are
not part of the project runtime. This does not remove the separately governed
real PP-OCRv5 document provider.

## Decision

Use one internal task-level model router with this policy-ordered execution set:

1. HiMed 8B served by vLLM for primary local inference;
2. an evaluation-selected smaller local summarizer for fast degraded summary generation only;
3. OpenAI API and Claude API through separate external-provider adapters and isolated Kafka consumer pools.

The order is not unconditional failover. The router selects only models approved for the task, language, facility, purpose, consent, data class and residency. If external processing is not permitted, failure of both local tiers produces a delayed/manual workflow.

## Consequences

- Product services depend on one versioned request/result contract, never a provider SDK.
- OpenAI and Claude credentials, quotas, concurrency, budgets, retries and circuit breakers are isolated by provider.
- External PHI processing stays disabled until legal/security review approves provider terms, data use/retention controls, residency and facility policy.
- All results retain provider/model/template/policy versions and provenance; no AI result becomes a signed record without clinician approval.
- The smaller summarizer must pass factuality, omission, Hindi/English, provenance, latency and hardware acceptance tests before selection.
