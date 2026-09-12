# Messaging Module

Kafka is the asynchronous transport from MVP, paired with PostgreSQL durable job state/outbox, schema registry, retry/dead-letter topics, replay tooling and lag monitoring. Primary HiMed, fast-local summary, OpenAI and Claude routes use isolated consumer groups and provider-specific bulkheads; completed/failed results use one normalized contract. Admission control bounds queue age/backlog, so Kafka is not an unlimited overflow buffer. Events use the reference-only envelope in `docs/contracts/EVENT-CATALOG.md`.
