# Reliability Plan

## Initial service objectives

Final targets require pilot traffic measurements. Start by defining and measuring:

- availability of registration, record view and clinician signing;
- p95 interactive API latency;
- p95 partial and final transcription latency;
- asynchronous document/summary completion time;
- notification delivery latency and duplicate rate;
- ABDM callback completion and reconciliation backlog;
- recovery point and recovery time for clinical records and documents.

## Required runbooks

- Database restore and point-in-time recovery.
- Object-store recovery and accidental access exposure.
- Kafka outage/outbox recovery, lag, poison message, dead-letter remediation and replay.
- Mock summary failure, deterministic fallback and manual-workflow activation.
- Elasticsearch outage, failed projection and scoped repair: follow
  [`PHASE-9-SEARCH-RUNBOOK.md`](PHASE-9-SEARCH-RUNBOOK.md).
- AI provider outage or unsafe-output spike.
- ABDM credential/callback failure.
- Notification provider outage.
- Patient identity merge incident.
- PHI exposure or suspected breach.
- Regional/facility outage and manual downtime workflow.

## Observability rules

- Use correlation IDs from edge through events and workers.
- Metrics use low-cardinality identifiers and never patient names/ABHA numbers.
- Traces exclude request/response bodies containing clinical data.
- Security audit is separate from debugging logs.
- Alert on user-visible symptoms and safety risks, not only CPU utilization.

Detailed dependency fallbacks, cache behavior, rollout controls and fault-injection cases are defined in `RESILIENCE-PATTERNS.md`.

## Phase 4 voice baseline

- Hindi controlled hospital-noise proxy: 14.21% mean WER, 0.63 s warm p95, 0.054 mean warm real-time factor on 10 samples.
- Spontaneous Indian English on CPU: 6.36% mean WER, 5.37 s warm p95, 0.552 mean warm real-time factor on 10 samples.
- Cold model initialization is outside the interactive SLO and must complete during readiness warmup.
- Alert separately on socket connection failures, no-speech/low-signal clarification rate, provider latency, queue publish failures, retained-audio upload failures and touch-fallback rate.
- Do not label the acoustic signal score as ASR confidence. Provider confidence remains nullable until calibrated.
- The small samples are regression smoke baselines. Pilot release requires consented hospital recordings, medical vocabulary coverage and clinician-approved per-language thresholds.
