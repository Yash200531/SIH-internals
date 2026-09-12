# Logical Services and MVP Deployables

The folders describe bounded capabilities and future extraction seams; they do not require one Kubernetes deployment each. The MVP deployment map is authoritative in `../docs/architecture/SERVICE-BOUNDARIES.md`.

- `clinical-platform`: modular transactional core.
- `conversation-orchestrator`: structured multilingual interview sessions.
- `ai-model-gateway`: model routing, credentials, safety and usage controls.
- `llm-runtime-vllm`: private vLLM deployment and approved model versions.
- `speech-service`: AI4Bharat/Bhashini-compatible ASR and Indic TTS routing.
- `clinical-nlp-service`: versioned PyTorch extraction/classification models.
- `rules-service`: deterministic clinician-approved red-flag and policy rules.
- `document-processing-worker`: scan, OCR and extraction pipeline.
- `summary-worker`: source-linked encounter and longitudinal summaries.
- `alert-worker`: deterministic clinical/workflow alerts.
- `notification-worker`: SMS/WhatsApp delivery with consent and deduplication.
- `abdm-adapter`: ABHA/ABDM protocol isolation and reconciliation.

Each logical service must document owned data, APIs/events, SLOs, privacy classification and failure behavior. A new physical service additionally requires a measured extraction trigger, operational owner, runbook and rollback plan.
