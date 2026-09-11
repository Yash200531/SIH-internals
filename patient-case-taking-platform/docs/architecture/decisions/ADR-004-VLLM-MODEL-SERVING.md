# ADR-004: Serve Candidate LLMs Through vLLM Behind the AI Gateway

## Status

Superseded by ADR-008 for this project. No generative-model download or vLLM
deployment is authorized. This decision does not prohibit the separately
governed real PP-OCRv5 document provider.

## Decision

Use vLLM as the initial LLM inference runtime. The AI model gateway is the only caller and exposes task-level clinical APIs rather than leaking the vLLM/OpenAI-compatible interface to product services.

HiMed 8B is the initial candidate model, not a clinically approved dependency. Approval requires license/provenance review, hardware and throughput benchmarks, Hindi/English and code-switch evaluation, hallucination and omission measurement, red-flag recall, privacy review and comparison with a recorded baseline.

## Consequences

- The gateway controls model selection, minimum-necessary context, prompt versions, timeouts, quotas and safety checks.
- Model replacement does not alter product-facing contracts.
- vLLM runs on private GPU infrastructure with no public endpoint.
- Manual case-taking and note entry remain available during inference failure.
- KServe or Ray Serve is considered later only when multi-model lifecycle or distributed scheduling requirements justify it.

## Exit criteria

- Candidate evaluation report is signed by AI and clinical-safety owners.
- Load tests establish supported concurrency, time-to-first-token and memory limits.
- Canary, rollback and model-version audit paths are demonstrated.
