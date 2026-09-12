# AI Model Gateway

Only approved boundary for model providers and managed inference. It is an internal model router, not the public API gateway. It owns provider policy, prompt/model versions, PHI minimization, deadline/admission decisions, token/cost limits and safety enforcement. Provider credentials are scoped to isolated provider worker pools rather than shared with callers or other pools.

Phase 5 defaults to an offline deterministic mock provider while task contracts,
safety rules, and supervised workflows are tested. HiMed/vLLM is a future,
separately approved route rather than a runtime dependency. A separately evaluated
smaller local summarizer may later provide degraded summary generation. OpenAI and
Claude remain isolated future adapters, never direct application dependencies.
Clients cannot choose arbitrary models. External routing requires explicit
task/facility/purpose/residency/provider eligibility and never occurs merely because
local GPUs are saturated. Every route passes through one versioned normalization
contract, and the gateway preserves manual/degraded paths.
