# Clinical assistance platform

## Current clinical-generation provider policy

The clinical dialogue and summary boundary is offline and mock-only. Set
`LLM_PROVIDER=mock`; any other value fails closed. The repository does not
download HiMed-8B, start vLLM, require OpenAI/Claude credentials or transmit
clinical context to a hosted generative API. ADR-008 records this decision.

The mock provider is deterministic contract scaffolding. It does not reason,
diagnose, prescribe or establish clinical accuracy. Invalid output is retried a
bounded number of times and then becomes a visibly degraded template draft.

## Implemented capabilities

- Hindi/English adaptive SOCRATES questions from a versioned ontology;
- deterministic Phase 6 urgent-symptom interruption;
- schema-constrained summary drafts from clinician-confirmed intake and active
  reviewed-document facts;
- source-path evidence, uncertainty and technical-completeness metadata;
- durable edit, reject, regenerate, submit-review and doctor sign-off workflow;
- metadata-only audit/outbox records that exclude prompts and clinical narrative.
- deterministic local mock TTS WAV cues plus an opt-in local IndicF5 provider;
- patient-confirmed intake persistence after editable accept/reject review.

The default speech-output provider is `TTS_PROVIDER=mock`. It uses no model,
credential or network and does not claim intelligible synthesis. The optional
`TTS_PROVIDER=indicf5` profile downloads the pinned AI4Bharat model artifacts,
then performs synthesis locally. It must be warmed before readiness and deployed
with ASR and LLM mock providers on the supported 6 GB GPU profile. English output
is best-effort because the published model card lists 11 Indian languages.
ADR-010 records the model, reference-voice, failure and resource boundaries.

ASR, TTS and OCR have separate provider boundaries. The dedicated document OCR
worker installs PaddlePaddle/PaddleOCR and defaults to the real CPU PP-OCRv5 mobile models; mock
OCR is retained for isolated tests. These packages are not summary dependencies,
and Phase 8 generation does not load ASR or OCR weights.

In short: `LLM_PROVIDER=mock` does not imply `OCR_PROVIDER=mock`. The supported
Compose defaults are `LLM_PROVIDER=mock` and `OCR_PROVIDER=paddleocr_fast`.

## Summary execution

1. A nurse or doctor confirms bounded encounter context.
2. The server recomputes deterministic warning flags.
3. The context assembler loads that confirmation plus active Phase 7 reviewed
   facts under tenant RLS. Raw OCR and client-asserted generated facts are excluded.
4. `LLMRouter` calls only `MockClinicalProvider` and validates the versioned schema.
5. The workflow stores the draft, evidence and provider metadata transactionally.
6. A clinician edits or rejects it. Only a doctor may sign an in-review version.
7. Signed content is hash-bound and locked; regeneration creates a new lineage version.

## Safety boundary

- Deterministic warning flags cannot be removed by provider output or draft editing.
- Confidence is structured completeness or fallback quality, never probability of diagnosis.
- Every draft says clinician review is required.
- Logs, audit records and events use opaque IDs, versions, status, provider and
  error class; narrative stays in the authorized clinical store.
- Model selection supplied by a client is ignored because there is no selectable model.
- Manual structured entry remains the fallback when generation is unavailable.

## Evaluation and change control

Engineering tests establish schema, lifecycle, isolation and failure behavior.
They do not establish clinical factuality, safety, usability or compliance.
Clinical, privacy/security, accessibility, operations and facility owners must
approve governed evidence before any real-patient use.

Introducing any generative provider requires explicit product authorization and
a new ADR covering provenance/license, deployment, privacy, residency, language
quality, hallucination/omission testing, security, rollback and operational cost.
It is not an automatic next step and must not be added as silent fallback.
