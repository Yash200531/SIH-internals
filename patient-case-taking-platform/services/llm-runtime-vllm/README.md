# vLLM Runtime

Future private GPU inference runtime behind the AI model gateway. Phase 5 uses
the offline mock provider and does not require this service. HiMed 8B remains an
unevaluated candidate and must not be enabled merely by changing configuration.
Any later runtime exposes no public or product-facing endpoint.

Owns model loading, tensor/quantization configuration, batching, GPU resource limits, health probes and inference metrics. It does not own prompts, clinical workflow, authorization or safety decisions.
