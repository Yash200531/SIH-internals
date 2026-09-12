# Context Graph

This document answers two questions: what each folder owns, and how information moves through the system.

## Repository context

```mermaid
flowchart TD
    ROOT["patient-case-taking-platform"]
    ROOT --> APPS["apps: user-facing channels"]
    ROOT --> SERVICES["services: logical capabilities and extraction seams"]
    ROOT --> PACKAGES["packages: versioned shared contracts"]
    ROOT --> MODELS["model-assets: prompts, cards and evaluations"]
    ROOT --> INFRA["infrastructure: environments and operations"]
    ROOT --> DOCS["docs: decisions, plans and controls"]
    ROOT --> TESTS["tests: release evidence"]
    ROOT --> TOOLS["tools: local and migration utilities"]

    APPS --> PATIENT["patient-pwa"]
    APPS --> CLINICIAN["clinician-web"]
    APPS --> KIOSK["assisted-kiosk"]
    APPS --> OPS["operations-console"]

    SERVICES --> CORE["clinical-platform"]
    SERVICES --> CONV["conversation-orchestrator"]
    SERVICES --> AIGW["ai-model-gateway + vLLM runtime"]
    SERVICES --> MODELSVC["speech, clinical NLP and rules services"]
    SERVICES --> WORKERS["document, summary, alert and notification workers"]
    SERVICES --> ABDM["abdm-adapter"]

    PACKAGES --> API["api-contracts"]
    PACKAGES --> EVENTS["event-contracts"]
    PACKAGES --> FHIR["fhir-profiles"]
    PACKAGES --> AUTHZ["authorization"]

    DOCS --> PLAN["build roadmap"]
    DOCS --> SAFETY["clinical safety"]
    DOCS --> SECURITY["security and privacy"]
    DOCS --> ADR["architecture decisions"]

    TESTS --> CONTRACT["contract tests"]
    TESTS --> CLINICAL["clinical safety evaluations"]
    TESTS --> E2E["end-to-end workflows"]
```

## Runtime context

```mermaid
flowchart LR
    subgraph USERS["People"]
        P["Patient / caregiver"]
        C["Doctor / nurse"]
        R["Reception / assisted operator"]
    end

    subgraph CHANNELS["Channels"]
        PP["Patient PWA"]
        CW["Clinician Web"]
        AK["Assisted Kiosk"]
    end

    CLERK["Clerk + hospital SSO adapter"]
    EDGE["CDN/WAF + load balancer + NGINX + public API gateway"]
    CORE["FastAPI Clinical Platform"]
    CONV["Conversation Orchestrator"]
    AI["Internal AI Model Router"]
    VLLM["vLLM / HiMed 8B primary"]
    FAST["Evaluated Smaller Local Summarizer"]
    EXT["OpenAI + Claude Isolated Provider Pools"]
    NORMALIZE["Result Normalization"]
    SPEECH["AI4Bharat/Bhashini ASR + Indic TTS"]
    OCR["OCR ensemble + clinical NLP"]
    RULES["Deterministic Rules Service"]
    BUS["Kafka Async Backbone"]
    WORKERS["Async Workers"]
    PG[("PostgreSQL")]
    MONGO[("MongoDB")]
    OBJ[("Object Storage")]
    REDIS[("Redis")]
    SEARCH[("Elasticsearch")]
    AUDIT[("Immutable Audit")]
    ABDM["ABDM / ABHA / HIE-CM"]
    HOSP["HIS / LIMS / PACS"]
    MSG["SMS / WhatsApp"]

    P --> PP
    C --> CW
    R --> AK
    PP --> EDGE
    CW --> EDGE
    AK --> EDGE
    PP --> CLERK
    CW --> CLERK
    CLERK --> CORE
    EDGE --> CORE
    CORE --> CONV
    CONV --> AI
    AI --> VLLM
    AI --> FAST
    AI -. policy-eligible only .-> EXT
    VLLM --> NORMALIZE
    FAST --> NORMALIZE
    EXT --> NORMALIZE
    CONV --> SPEECH
    WORKERS --> OCR
    CONV --> RULES
    CORE --> PG
    WORKERS --> MONGO
    CORE --> REDIS
    CORE --> OBJ
    CORE --> BUS
    BUS --> WORKERS
    WORKERS --> OBJ
    WORKERS --> PG
    WORKERS --> SEARCH
    CORE --> AUDIT
    WORKERS --> AUDIT
    CORE <--> ABDM
    CORE <--> HOSP
    WORKERS --> MSG
```

## Primary clinical flow

```mermaid
sequenceDiagram
    actor Patient
    participant App as Patient/Kiosk App
    participant Core as Clinical Platform
    participant Conv as Conversation Orchestrator
    participant AI as AI Model Gateway
    participant Doctor as Clinician Web
    participant Record as Clinical Record

    Patient->>App: Speak or enter complaint
    App->>Core: Start encounter
    Core->>Conv: Start structured interview
    Conv->>AI: ASR/NLP request with minimum necessary context
    AI-->>Conv: Transcript, entities, confidence and provenance
    Conv-->>App: Confirm interpreted answer
    Patient->>App: Correct or approve
    App->>Core: Submit confirmed answer
    Core-->>Doctor: Draft encounter summary and unresolved questions
    Doctor->>Record: Correct and sign clinical note
    Record-->>Patient: Produce patient-friendly explanation
```

## Dependency direction

- Apps depend on public API contracts, never service internals.
- Workers consume versioned events and call owned service APIs where necessary.
- The AI gateway depends on safety policy and model configuration, not clinical database tables.
- The public API gateway cannot select a model/provider; only the internal model router may route to policy-approved local or external pools.
- ABDM and messaging providers are isolated behind adapters.
- Tests depend on published contracts and observable outcomes.
- Infrastructure deploys services but contains no clinical business rules.
