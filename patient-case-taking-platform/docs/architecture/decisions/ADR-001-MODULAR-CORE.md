# ADR-001: Start with a Modular Clinical Core

## Status

Proposed.

## Decision

Implement patient identity, consent, encounters and signed clinical records as modules in one deployable clinical platform for the MVP. Keep schema ownership and APIs explicit so modules can be extracted later.

## Why

These capabilities participate in evolving transactional workflows. A premature microservice split would add distributed failure and consistency costs before service boundaries are validated.

## Consequences

- Faster workflow iteration and simpler transactions.
- Strong module-boundary tests are mandatory.
- AI, document, notification and ABDM workloads remain separate due to scaling and isolation needs.

