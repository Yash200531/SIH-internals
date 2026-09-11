# ADR-008: Use only the offline mock provider for clinical summaries

## Status

Accepted — 2026-09-04. Supersedes ADR-004 and ADR-007 for this project.

## Context

Earlier planning named HiMed-8B on vLLM and OpenAI/Claude fallbacks. Those
systems were never implemented or validated, would add model downloads,
credentials, network transport and clinical-data governance obligations, and
conflict with the confirmed product requirement to use the mock provider.

Phase 8 needs a dependable workflow contract, provenance, persistence and
clinician review before model selection is useful. The existing deterministic
mock provider already exercises the same versioned request/response boundary
without inference, downloads or external traffic.

## Decision

MediKiosk summary generation uses `LLM_PROVIDER=mock` only. Runtime dependencies,
Compose, setup instructions and CI must not install or invoke HiMed-8B, vLLM,
OpenAI, Claude or another generative model. Any other configured provider fails
closed. After bounded retries on malformed mock output, a deterministic template
produces a visibly degraded draft for manual review.

The Phase 8 product API accepts encounter identifiers, not generated clinical
facts. It assembles clinician-confirmed context and reviewed document facts on
the server, preserves deterministic warning flags and requires doctor sign-off.

## Alternatives considered

### HiMed-8B through vLLM

Rejected for this project: requires model artifacts and serving infrastructure,
and no repository evidence establishes its license fit or clinical performance.

### Hosted OpenAI or Claude APIs

Rejected for this project: conflicts with the no-API requirement and introduces
credentials, external transport, retention/residency and provider governance.

### Browser-generated or client-supplied summaries

Rejected: the client is not an authoritative clinical source and could omit
warning flags or inject unsupported assertions.

## Consequences

- Local setup needs no GPU, model weights or generative-provider API key.
- Generated text is deterministic scaffolding, not a clinically validated model output.
- Provider metadata remains in the contract so the boundary can be reconsidered
  only through a new ADR and explicit user authorization.
- Clinician workflow, storage, authorization, provenance and safety tests remain
  meaningful and are reusable if an approved provider is ever introduced.
