# ADR-005: Separate Realtime Delivery From Durable Events

## Status

Accepted; implemented for the Phase 4 voice slice. Durable outbox integration remains pending.

## Decision

Use authenticated WebSockets for partial transcripts, progress and time-sensitive UI updates. Use Kafka from MVP for asynchronous workflows, isolated consumer groups, replay and dead-letter handling. PostgreSQL retains durable workflow/job state and the transactional outbox. Redis remains cache/session/rate-limit and optional idempotency acceleration, not the queue source of truth.

## Consequences

- WebSocket messages are disposable delivery hints and never the authoritative clinical state.
- FastAPI/PostgreSQL commits durable workflow changes before the transactional outbox publishes events.
- Queue/broker payloads carry metadata and internal artifact IDs, not raw audio, unrestricted transcripts, prompts, completions or document bodies.
- Consumers are idempotent and use schema versions, bounded retries and dead-letter handling.
- PostgreSQL unique constraints and a processed-event ledger provide correctness; Redis keys may accelerate checks but are not the idempotency source of truth.
- Interactive ASR uses the streaming path rather than waiting for queue round trips.
- The implemented ASR completion event is metadata-only and excludes raw audio and transcript content. Redis turn context expires; optional audio retention requires separate consent and application-layer AES-256-GCM encryption before object storage.

## Exit criteria

- Reconnect/resume behavior is tested without duplicating confirmed answers.
- Retried or replayed jobs produce the same final projection.
- Broker outage does not prevent manual clinical note entry/signing.
