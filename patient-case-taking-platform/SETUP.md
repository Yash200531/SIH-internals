# MediKiosk Setup and Usage Guide

This guide is for developers, designers and reviewers starting MediKiosk on a new device. The recommended path uses Docker Compose and works on Windows, macOS and Linux.

> **Prototype notice:** the current dashboards use synthetic demonstration content. Do not enter real patient information. AI-assisted text is a draft and is not a diagnosis, prescription or signed medical record.

## 1. What starts locally

| Service | Address | Purpose |
|---|---|---|
| Patient experience | <http://localhost:3000> | Bilingual intake, consent, uploads and signed reports |
| Nurse dashboard | <http://localhost:3001> | Triage, vitals, alerts and handoffs |
| Doctor dashboard | <http://localhost:3001/doctor> | Evidence review, editing and sign-off |
| Clinical search | <http://localhost:3001/search> | Authorized reviewed-record search and longitudinal timeline |
| Document review | <http://localhost:3001/documents/review> | Source-adjacent prescription candidate review |
| Admin console | <http://localhost:3002> | Workforce and facility administration scaffold |
| API | <http://localhost:8000> | FastAPI application |
| API documentation | <http://localhost:8000/docs> | Interactive development API reference |
| MinIO console | <http://localhost:9002> | Local object-storage administration |

PostgreSQL, MongoDB, Redis, Kafka, Elasticsearch and MinIO also run locally
through Docker. Their data persists in named Docker volumes.

## 2. Prerequisites

### Recommended Docker setup

- Git 2.40 or newer
- Docker Desktop on Windows/macOS, or Docker Engine with the Compose plugin on Linux
- At least 8 GB RAM available to Docker
- Ports `3000`, `3001`, `3002`, `5432`, `6379`, `8000`, `9000`, `9002`,
  `9092`, `9200` and `27017` available

Verify the tools:

```bash
git --version
docker --version
docker compose version
```

### Frontend-only development

Install Node.js 22 LTS and npm 10 or newer. Python is not required when working only on the synthetic dashboard UI.

### Backend development outside Docker

Install Python 3.11 or newer. Docker is still the simplest way to run PostgreSQL, MongoDB, Redis, Kafka and MinIO.

## 3. Clone and configure

```bash
git clone https://github.com/shivamsingh-007/NotMID.git
cd NotMID/patient-case-taking-platform
```

Create the local environment file.

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

macOS/Linux:

```bash
cp .env.example .env
```

The checked-in values are local-only placeholders. Never reuse them for a shared, pilot or production environment. Clerk keys may remain empty for the current local prototype.

For the complete local demo, including Phase 5 assisted questions and the
Phase 7 document APIs, edit `.env` and set:

```dotenv
ENABLE_DEMO_ROUTES=true
DOCUMENT_WORKFLOW_ENABLED=true
SUMMARY_WORKFLOW_ENABLED=true
LLM_PROVIDER=mock
OCR_PROVIDER=paddleocr_fast
TTS_PROVIDER=mock
DOCUMENT_OCR_AUTOMATION_ENABLED=true
DOCUMENT_EXTRACTION_AUTOMATION_ENABLED=true
```

Provider names are independent; `mock` does not describe the whole AI stack:

| Capability | Local provider | Runtime status |
|---|---|---|
| Clinical dialogue and summaries | `LLM_PROVIDER=mock` | Offline deterministic contract scaffolding |
| Document OCR | `OCR_PROVIDER=paddleocr_fast` | Real CPU PP-OCRv5 mobile detector and recognizer |
| Speech output | `TTS_PROVIDER=mock` | Deterministic WAV cue, not production speech synthesis |

The default document path therefore does **not** use mock OCR. The mock OCR
adapter is retained only for isolated development and contract tests.

`mock` is the only supported clinical dialogue/summary provider. The local
stack does **not** start vLLM, download HiMed weights, require a GPU, ask for an
OpenAI/Claude key, or send patient text to an external model API. A different
`LLM_PROVIDER` value makes the Phase 8 API fail closed.
The document worker uses the real CPU PP-OCRv5 mobile detector and recognizer. On its first start it
downloads official PaddleOCR model artifacts into named Docker cache volumes;
no API key is required. `OCR_PROVIDER=mock` remains available only for isolated
development/tests. Real inference is still engineering evidence, not clinical
accuracy validation. The local mock TTS WAV cue is contract scaffolding, not
production speech.

## 4. Start everything with Docker

Build and start the complete local stack:

```bash
docker compose up --build
```

The first build downloads images and installs dependencies, so it can take several minutes. Compose applies migrations before starting the API and workers. Wait until the API, three Next.js services, ClamAV and document workers report ready/running.

Run in the background instead:

```bash
docker compose up --build -d
docker compose ps
```

Verify the API:

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

PowerShell alternative:

```powershell
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/readyz
```

Open the dashboard URLs from the table in section 1.

The Compose topology intentionally has no vLLM service. Dialogue and summaries
use the mock provider, the document worker uses real PP-OCRv5, and TTS returns a
local deterministic WAV cue. PP-OCRv5 downloads its public weights on first use;
no component needs a hosted inference API or API key.

To verify the mock clinical assistant after enabling demo routes:

```bash
curl http://localhost:8000/api/v1/clinical-ai/health
```

The response should report `"provider":"mock"`, `"ready":true` and `"external_network_used":false`. Then open <http://localhost:3000/case-taking/assisted>.

Verify the actual OCR model after the first worker build/download:

```bash
docker compose run --rm --no-deps document-ocr-worker python -m tools.verify_real_ocr
```

The command must print `PASS provider=paddleocr_fast model=PP-OCRv5-mobile`. It creates
only a synthetic printed image in memory; it does not use a patient document.

To exercise the Phase 6 Slice 6.1 contract with synthetic data:

```bash
curl -X POST http://localhost:8000/api/v1/triage/evaluate \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"11111111-1111-4111-8111-111111111111","facility_id":"22222222-2222-4222-8222-222222222222","encounter_id":"33333333-3333-4333-8333-333333333333","input_version":1,"idempotency_key":"setup-example-1","language":"en","chief_complaint":"My chest feels heavy","confirmed_answers":{}}'
```

PowerShell alternative:

```powershell
$triageBody = @{
  tenant_id = "11111111-1111-4111-8111-111111111111"
  facility_id = "22222222-2222-4222-8222-222222222222"
  encounter_id = "33333333-3333-4333-8333-333333333333"
  input_version = 1
  idempotency_key = "setup-example-1"
  language = "en"
  chief_complaint = "My chest feels heavy"
  confirmed_answers = @{}
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/triage/evaluate -ContentType "application/json" -Body $triageBody
```

The response should use `phase6.prototype.v1`, return the stable rule ID
`RF-CARDIAC-001`, and state `"durable_alert_created":false`. A result of
`no_configured_flag` means only that no configured prototype rule matched; it
does not mean routine or safe.

### Stop the stack

```bash
docker compose down
```

This preserves database volumes. To remove local databases and object-storage data as well, run `docker compose down --volumes` only when you intentionally want to erase the local development data.

If migration startup reports a checksum mismatch, the named volume was created
from an older edited development migration. Do not alter the stored checksum or
edit an already released migration. Preserve any data you need, then either use
a fresh database or—only for disposable local data—run `docker compose down
--volumes` before starting again. That command erases all local Compose database
and object-storage volumes.

### Use the Phase 7 document review locally

Development authentication is available only when `ENABLE_DEMO_ROUTES=true`.
Create a synthetic doctor token (never use this route outside local development):

```bash
curl -X POST "http://localhost:8000/api/v1/auth/token?user_id=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa&email=doctor%40example.test&role=doctor&tenant_id=11111111-1111-4111-8111-111111111111&facility_ids=22222222-2222-4222-8222-222222222222"
```

Copy the returned `token` value, open the clinician console browser developer
console, and run:

```javascript
sessionStorage.setItem("medikiosk.access_token", "PASTE_TOKEN_HERE");
location.assign("/documents/review");
```

The queue is empty until a document is registered and reaches
`review_required`. Use the API documentation at <http://localhost:8000/docs>
to exercise the authorized upload-init/finalize endpoints with synthetic PNG,
JPEG, WebP or bounded PDF data. The pipeline runs quarantine → ClamAV scan →
page normalization → OCR → prescription extraction. In the review screen,
inspect the short-lived source preview, then accept, correct or reject each
candidate before finalizing. Accepted/corrected facts are promoted with
`document_stated` semantics; review does not assert that a medication is current.

If OCR or extraction is disabled or fails after pages were normalized, an
authorized nurse/doctor can open manual review through
`POST /api/v1/document-reviews/{document_id}/manual`, add source-linked manual
candidates, and finalize normally. See the
[document-pipeline runbook](infrastructure/runbooks/PHASE-7-DOCUMENT-PIPELINE.md).

### Use the Phase 8 summary workflow locally

Enable `ENABLE_DEMO_ROUTES=true` and `SUMMARY_WORKFLOW_ENABLED=true`. Open
<http://localhost:3001/login>, choose **Doctor**, and enter synthetic UUIDs for
the user, tenant and permitted facility. **Start local clinical session** obtains
the demo token from the local API and opens `/doctor`; no browser-console setup
is required. This login is deliberately demo-gated and is not production SSO.

In <http://localhost:8000/docs>, authorize with `Bearer PASTE_TOKEN_HERE` and:

1. `PUT /api/v1/summary-workflows/contexts` to confirm a synthetic encounter's
   facility, patient, chief complaint and answers. Use UUIDs and a facility ID
   included in the token.
2. `POST /api/v1/summary-workflows/generate` with the same facility, patient and
   encounter IDs and an `Idempotency-Key`. Do not send clinical narrative to
   this endpoint; the server loads the confirmed context.
3. Open <http://localhost:3001/doctor>, paste the encounter UUID and choose
   **Load summary**.
4. Edit and **Save draft**, or provide a reason and **Reject**. A rejected/draft
   version can be **Regenerated** as a separate generation.
5. Choose **Submit review**, then **Sign & lock** as a doctor. Signed content is
   immutable. This engineering signature is an integrity hash, not a legal
   digital-signature claim.

Nurses may confirm, generate, read and submit, but cannot edit, reject,
regenerate or sign. Warning flags are read-only. Use synthetic data only; this
workflow has engineering tests but no clinical/production approval.

### Use Phase 9 clinical search locally

Keep the complete demo flags from section 3 enabled. Compose starts
Elasticsearch 9.3.0 and `search-index-worker`; the worker consumes only signed
summary and reviewed-document events and rebuilds its derived index from
PostgreSQL. Raw OCR and unsigned drafts are never indexed.

1. Open <http://localhost:3001/login> and start a synthetic Doctor or Nurse
   session with tenant, user and facility UUIDs.
2. Choose **Clinical search** in the navigation and enter the synthetic patient
   UUID. Confirm **Treatment purpose** before opening any record.
3. Search reviewed text, use the source/date/fact-type filters, or switch to the
   chronological timeline. Empty and unavailable states do not expose raw
   backend details.
4. Doctors may export a private, formula-neutralized CSV. Nurses see the
   doctor-only policy and receive 403 if they call the export API directly.
5. Patient sessions use <http://localhost:3000/records>; that `/me` route shows
   the same longitudinal reviewed sources without accepting a patient ID from
   the browser.

Run reconciliation before and after a tenant repair. These commands compare
opaque record IDs only and print machine-readable counts; a mismatch exits
non-zero. Replace the example with a synthetic/local tenant UUID.

```bash
docker compose run --rm search-index-worker python -m app.search.worker reconcile-tenant --tenant-id 11111111-1111-4111-8111-111111111111
docker compose run --rm search-index-worker python -m app.search.worker rebuild-tenant --tenant-id 11111111-1111-4111-8111-111111111111
```

`rebuild-tenant` deletes and reloads only that tenant in the derived alias, then
reconciles IDs and counts. It never changes PostgreSQL clinical truth. The
versioned whole-index alias swap is exercised by the integration/benchmark
path; do not replace a shared alias from an incomplete tenant list.

Run the disposable correctness/latency benchmark:

```bash
docker compose run --rm search-index-worker python -m tools.verify_phase9_search --record-count 250 --iterations 5
```

The verifier creates an isolated alias, loads a deterministic synthetic corpus,
checks English synonym, medication, allergy, Hindi and cross-tenant isolation
cases, reports observed local latency, reconciles IDs and removes its indices.
Its output is engineering evidence, not a production load or clinical-relevance
claim.

### Use the patient workflow locally

Enable the complete demo flags from section 3, then open
<http://localhost:3000>. The production patient runtime is
`apps/patient-kiosk`; `frontend/apps/patient-dashboard` is a non-runtime scaffold.

1. Choose **Start case taking**. The app creates an opaque kiosk session and a
   synthetic patient development session; no record data is available to the
   kiosk pre-auth token.
2. Review and grant bounded treatment consent. The consent is stored in
   PostgreSQL and can later be revoked from <http://localhost:3000/consents>.
3. Choose **Assisted questions**. Confirm or correct each captured answer before
   it feeds the next mock-provider SOCRATES question. The mock TTS control plays
   an acknowledgement tone, not intelligible clinical speech.
4. Accept or reject the editable summary draft. That decision is durably stored
   as patient-confirmed intake; it is not a signed record.
5. Open <http://localhost:3000/records/upload> to upload a synthetic PNG, JPEG,
   WebP or bounded PDF. The patient ID is taken from the token, the object goes
   directly to quarantine, and the UI reports the real scan/OCR/review state.
6. Open <http://localhost:3000/records> to see only clinician-signed reports and
   clinician-reviewed document facts. Drafts and raw OCR are deliberately absent.

All patient record APIs are under `/api/v1/patient-portal/me`. They derive the
patient, tenant and permitted facilities from the token. See
[`docs/contracts/PATIENT-PORTAL-API.md`](docs/contracts/PATIENT-PORTAL-API.md).

## 5. Frontend-only development

Run each application in a separate terminal. The API URL defaults to
`http://localhost:8000`. The doctor page and patient records, consent and upload
pages require the API and a stored development token. Nurse-only demonstration
cards still contain clearly labelled synthetic content.

### Patient experience — port 3000

```bash
cd apps/patient-kiosk
npm ci
npm run dev -- --port 3000
```

### Nurse and doctor experience — port 3001

```bash
cd apps/clinician-console
npm ci
npm run dev -- --port 3001
```

### Admin console — port 3002

```bash
cd apps/admin-console
npm ci
npm run dev -- --port 3002
```

When running a frontend against a different API, copy its `.env.example` to `.env.local` and update `NEXT_PUBLIC_API_URL` before starting the development server.

## 6. Backend development outside Docker

Start only the infrastructure services:

```bash
docker compose up -d postgres mongodb redis kafka minio minio-init clamav
```

Create and activate a virtual environment.

Windows PowerShell:

```powershell
cd apps/api
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
python -m app.migrations up
uvicorn app.main:app --reload --port 8000
```

macOS/Linux:

```bash
cd apps/api
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env
python -m app.migrations up
uvicorn app.main:app --reload --port 8000
```

Dialogue and TTS remain mocks. The dedicated Compose OCR worker includes the
real PP-OCRv5 mobile CPU runtime and downloads its public model artifacts into named
cache volumes on first start. When running that worker directly, install
`.[dev,ai-ocr-fast]`; a Hugging Face credential is not required because the
documented local configuration uses Paddle's public BOS model source.

### Enable real Hindi and English ASR in Docker

The default lightweight API image uses mock speech. For real transcription, set
these values in the repository `.env` before rebuilding the API:

```dotenv
API_BUILD_TARGET=asr
ASR_PROVIDER=ai4bharat
ASR_CPU_THREADS=4
ASR_DECODING=ctc
ASR_ENGLISH_PROVIDER=whisper
ASR_ENGLISH_MODEL=openai/whisper-small.en
VOICE_REDIS_ENABLED=true
VOICE_KAFKA_ENABLED=true
```

If the Hindi model requires access approval, accept its access conditions and
set `HUGGINGFACE_TOKEN` locally. Keep the token out of Git. Run
`docker compose up -d --build api`; the selected image installs the speech
dependencies and preserves downloaded models in `asr-model-cache`. Hindi uses
the pinned Indic Conformer revision and English uses Whisper small.en. First
use includes model download/loading time. `ASR_WARMUP_ON_START=true` moves
speech loading to startup without loading OCR in the API (OCR has its own worker).
A missing dependency or unavailable model must remain a
visible failure with manual entry available; it is not a successful transcript.

The Redis and Kafka switches enable the existing voice context and metadata
adapters. They do not enable audio retention. This setup does not install TTS
or HiMed 8B. Verify with synthetic speech in both languages before a showcase.

`ASR_CPU_THREADS` bounds OpenMP/MKL threads in the API container. For local
Python runs, set `OMP_NUM_THREADS` and `MKL_NUM_THREADS` before starting Python.
Measure on your machine with other heavy builds stopped; increasing thread
counts can worsen latency through CPU contention. Local voice fallback history
is capped at 128 turns/events, and contexts expire lazily on access after the
configured TTL. With Redis/Kafka enabled, the adapter does not also retain local
copies. Encrypted audio is uploaded to object storage without a persistent
in-process copy.

### Enable local IndicF5 TTS on a 6 GB NVIDIA GPU

IndicF5 is opt-in. It uses AI4Bharat's official Transformers custom-model API;
the similarly named generic `f5-tts` PyPI package is not a compatible loader.
Accept the model conditions at <https://huggingface.co/ai4bharat/IndicF5> and
authenticate locally without committing the token.

Run only one real GPU model in this profile. Keep ASR and the clinical LLM on
their mock providers while IndicF5 is resident:

```dotenv
TTS_PROVIDER=indicf5
TTS_WARMUP_ON_START=true
TTS_SYNTHESIS_TIMEOUT_SECONDS=180
INDICF5_DEVICE=cuda
INDICF5_NFE_STEPS=16
INDICF5_CACHE_ENTRIES=32
ASR_PROVIDER=mock
LLM_PROVIDER=mock
HUGGINGFACE_TOKEN=hf_your_local_token
```

For Docker Desktop with NVIDIA GPU support, the checked-in override selects the
TTS image, requests one GPU and enforces the mock ASR/LLM profile:

```powershell
docker compose -f docker-compose.yml -f docker-compose.tts.yml up -d --build api
```

For a native Windows environment, install the CUDA wheel before the project
extra so pip cannot silently select a CPU-only build:

```powershell
cd apps/api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install --no-cache-dir torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128
python -m pip install --no-cache-dir -e ".[dev,ai-tts-f5]"
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

`torch.cuda.is_available()` must print `True`. Start the API without `--reload`
because a reload worker can briefly duplicate the model in VRAM. Warmup moves
the gated downloads and model construction ahead of readiness, avoiding a
patient request paying the cold-start cost:

```powershell
$env:TTS_PROVIDER="indicf5"
$env:TTS_WARMUP_ON_START="true"
$env:INDICF5_DEVICE="cuda"
$env:INDICF5_NFE_STEPS="16"
$env:ASR_PROVIDER="mock"
$env:LLM_PROVIDER="mock"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Test with synthetic Hindi text:

```powershell
$body = @{ text = "नमस्ते, कृपया बताइए आपको कहाँ दर्द हो रहा है?"; language = "hi"; voice = "calm" } | ConvertTo-Json
Invoke-WebRequest -Method Post -Uri http://127.0.0.1:8000/api/v1/tts/synthesize -ContentType application/json -Body $body -OutFile indicf5-smoke.wav
```

The default reference is AI4Bharat's published Punjabi prompt and its matching
transcript. Do not replace it with patient speech or clone another person's
voice without explicit permission. English output is best-effort; IndicF5's
published support claim covers 11 Indian languages. Manual reading of visible
text remains available if synthesis fails. `INDICF5_NFE_STEPS=16` is the tested
low-latency profile; increase it up to 32 if a deployment's listening evaluation
prefers the slower default-quality tradeoff. Prepared reference data and up to
`INDICF5_CACHE_ENTRIES` generated prompts are cached per process, and the
patient dialogue client reuses in-flight synthesis when it auto-plays the next
clinical question.

## 7. How to use the prototype

### Patient

1. Open <http://localhost:3000>.
2. Switch between Hindi and English.
3. Start a case, review the treatment consent and choose voice-assisted or manual entry.
4. In **Assisted questions**, record or type an answer, confirm/correct it, and
   continue through adaptive SOCRATES questions from the offline mock provider.
5. Edit and accept/reject the summary draft; the API stores the real decision.
6. Use **My records** to view/download signed reports, review the reviewed-fact
   timeline, manage consent and upload a synthetic document into the OCR pipeline.
7. Use the accessibility controls to test larger text, higher contrast and
   assistant/emergency status announcements.

Browser microphone permission is needed only when exercising real recording components. Do not record real patient conversations in local development.

### Nurse

1. Sign in at <http://localhost:3001/login> as a synthetic nurse or doctor with
   the same tenant and facility used by the patient session.
2. Open <http://localhost:3001> or `/worklist`, confirm treatment purpose and
   choose **Load worklist**. Accepted, consent-authorized patient submissions
   load from PostgreSQL; there are no hardcoded patients or shift counts.
3. Choose **Review intake**, inspect the complaint and patient-confirmed answers,
   then explicitly confirm that you reviewed them.
4. Choose **Prepare handoff** to confirm the authoritative context and generate
   a draft. Retry reopens an existing generation. No signing happens here.
5. Choose **Open clinician review**, then **Load summary**. Doctors can edit,
   submit and sign; nurses retain their restricted Phase 8 permissions.

The worklist requires DOCUMENT_WORKFLOW_ENABLED and SUMMARY_WORKFLOW_ENABLED.
No database migration is needed for this projection. To roll back the UI/API
change, redeploy the preceding version; stored intake and summary history remain
intact. This worklist does not claim to provide Phase 6 durable alert escalation.

To create a synthetic intake for a walkthrough, run from `apps/api`:

```bash
python -m tools.seed_showcase
```

The helper requires the demo routes and durable workflows to be enabled. It
calls only a localhost API, creates a new synthetic tenant/patient/encounter,
grants 24-hour treatment consent and submits an accepted intake. It prints the
tenant, facility and doctor UUIDs to enter at the clinical sign-in screen; it
does not print credentials. Each run creates a separate sample. This verifies
the handoff without requiring a microphone, and does not replace ASR/OCR tests.

### Doctor

1. Open <http://localhost:3001/doctor>.
2. Paste a synthetic encounter UUID whose context and draft were created through the API.
3. Compare each editable section with its evidence paths and visible uncertainties.
4. Save the draft, reject/regenerate when necessary, or submit it for review.
5. Sign an in-review draft. The durable version is locked after signing.

## 8. Development checks

Run these inside each frontend application:

```bash
npm run lint
npm run build
```

Run API tests:

```bash
cd apps/api
pytest
ruff check app tests
mypy app
```

Run the live Phase 7 integration suite while the Compose infrastructure is up.

Windows PowerShell:

```powershell
$env:PHASE7_INTEGRATION = "1"
pytest tests/test_phase7_document_integration.py tests/test_phase7_ocr_integration.py -q
Remove-Item Env:PHASE7_INTEGRATION
```

macOS/Linux:

```bash
PHASE7_INTEGRATION=1 pytest tests/test_phase7_document_integration.py tests/test_phase7_ocr_integration.py -q
```

Run the Phase 8 unit/API tests and live PostgreSQL suite:

Windows PowerShell:

```powershell
pytest tests/test_phase8_summary_service.py tests/test_phase8_summary_api.py tests/test_phase8_outbox_publisher.py -q
$env:PHASE8_INTEGRATION = "1"
pytest tests/test_phase8_summary_integration.py -q
Remove-Item Env:PHASE8_INTEGRATION
```

macOS/Linux:

```bash
pytest tests/test_phase8_summary_service.py tests/test_phase8_summary_api.py tests/test_phase8_outbox_publisher.py -q
PHASE8_INTEGRATION=1 pytest tests/test_phase8_summary_integration.py -q
```

Run the Phase 9 unit/API suite and the real Elasticsearch/Kafka/audit checks:

Windows PowerShell:

```powershell
pytest tests -k phase9 -q
$env:PHASE9_INTEGRATION = "1"
$env:PHASE9_KAFKA_INTEGRATION = "1"
$env:PHASE9_POSTGRES_INTEGRATION = "1"
pytest tests/test_phase9_search_integration.py tests/test_phase9_search_kafka_integration.py tests/test_phase9_search_audit_integration.py -q
Remove-Item Env:PHASE9_INTEGRATION
Remove-Item Env:PHASE9_KAFKA_INTEGRATION
Remove-Item Env:PHASE9_POSTGRES_INTEGRATION
```

macOS/Linux:

```bash
pytest tests -k phase9 -q
PHASE9_INTEGRATION=1 PHASE9_KAFKA_INTEGRATION=1 PHASE9_POSTGRES_INTEGRATION=1 pytest tests/test_phase9_search_integration.py tests/test_phase9_search_kafka_integration.py tests/test_phase9_search_audit_integration.py -q
```

Run the self-scoped patient portal integration suite against the same local
PostgreSQL service. It creates and removes an isolated schema and does not touch
the application's `public` schema.

Windows PowerShell:

```powershell
$env:PATIENT_PORTAL_INTEGRATION = "1"
pytest tests/test_patient_portal_integration.py -q
Remove-Item Env:PATIENT_PORTAL_INTEGRATION
```

macOS/Linux:

```bash
PATIENT_PORTAL_INTEGRATION=1 pytest tests/test_patient_portal_integration.py -q
```

Run the frozen synthetic prescription-extraction evaluation:

```bash
python tools/evaluate_phase7_extraction.py ../../tests/model-evaluations/phase7/manifest.jsonl
```

Its perfect candidate score covers seven synthetic OCR-region fixtures only.
It does not measure real OCR, handwriting, camera quality or clinical safety,
and release thresholds still require owner approval.

Inspect container logs:

```bash
docker compose logs -f api
docker compose logs -f patient-kiosk clinician-console
```

## 9. Troubleshooting

### A port is already in use

Stop the conflicting process or change the host-side port in `docker-compose.yml`. Keep `CORS_ALLOWED_ORIGINS` aligned with any new frontend origins.

### Docker reports an unhealthy dependency

```bash
docker compose ps
docker compose logs postgres mongodb redis kafka
```

Restart the affected service after reviewing its log:

```bash
docker compose restart <service-name>
```

### A frontend cannot reach the API

- Confirm <http://localhost:8000/healthz> responds.
- Confirm `NEXT_PUBLIC_API_URL=http://localhost:8000`.
- Restart the Next.js process after changing an environment file.
- Confirm the frontend origin is present in `CORS_ALLOWED_ORIGINS`.

### Shared design-system CSS cannot be resolved

Run commands from the repository paths shown above. The patient and clinician apps intentionally resolve `packages/ui-system` through the repository-level Next.js build root.

### OneDrive or antivirus makes builds slow on Windows

Clone the repository into a short local path outside a synchronized folder, such as `C:\dev\NotMID`, and exclude project `node_modules` and `.next` directories from real-time indexing where organizational policy permits.

### Reset only generated frontend output

Stop the development server, remove the affected app's `.next` directory, and run the build again. Do not remove database volumes unless a full local-data reset is intended.

## 10. Current limitations

- Patient consent, confirmed intake, document state and signed-report views use
  durable APIs. Local identity remains a synthetic demo boundary; do not use it
  with real patient information.
- Phase 8 sign-off is durable, version-locked and hash-bound, but the engineering
  integrity hash is not represented as a legally qualified digital signature.
- Clerk and hospital SSO integration are not required for the local prototype and are not production-configured.
- Demo API routes are disabled by default. Set `ENABLE_DEMO_ROUTES=true` in `.env` only for local contract/UI prototyping; those routes do not provide production authorization or persistence guarantees.
- Phase 5 intentionally has no vLLM integration. Any generative provider requires separate clinical, privacy, licensing and rollback approval.
- Mock TTS emits a deterministic acknowledgement WAV, not intelligible speech.
  Production bilingual TTS needs separate accessibility, privacy and quality approval.
- Phase 6 provides prototype evaluation, durable patient-triggered flags, staff
  ownership, acknowledgement, explicit resolution and Kafka outbox publication.
  Governed handoff/override, timed escalation, notification consumers, clinical
  approval and measured clinical validation remain incomplete.
- Phase 7 is an engineering candidate for prescription documents. Durable
  registry/quarantine, scan/normalization/OCR/extraction workers, source-adjacent
  review, reviewed-fact promotion and an outbox publisher are implemented and
  integration-tested locally. Real OCR/camera/handwriting evaluation,
  accessibility sessions, operational drills and owner approvals remain open.
- Lab-table extraction is deliberately deferred until a governed table/unit/
  locale evaluation set and thresholds are approved.
- Production deployment requires managed secrets, TLS, authenticated data services, backups, monitoring and reviewed clinical-safety controls.

For product behavior see [`PRODUCT.md`](PRODUCT.md). For the visual system see [`DESIGN.md`](DESIGN.md). For architecture and safety constraints start with [`CONTEXT-GRAPH.md`](CONTEXT-GRAPH.md) and [`AGENTS.md`](AGENTS.md).

## Full synthetic OCR pipeline check

After starting the documented local demo configuration and document workers,
run from `apps/api`:

```powershell
.\.venv\Scripts\python.exe -m tools.verify_document_pipeline
```

This uploads a generated prescription via the patient API and MinIO grant,
waits for scanning/normalization/real OCR/extraction, and checks exact expected
source-linked candidates. It verifies that unreviewed OCR is absent from the
patient timeline, then makes explicit simulated clinician review decisions for
that known synthetic fixture and verifies document-stated timeline facts.
It never signs a summary. It creates synthetic records in a new tenant each run.
Linux callers must pass `--font /path/to/font.ttf`.

## Durable prototype alerts

Apply current migrations and set `TRIAGE_WORKFLOW_ENABLED=true` alongside
`ENABLE_DEMO_ROUTES=true` and `DOCUMENT_WORKFLOW_ENABLED=true` for the local demo.
After reviewing a consented accepted intake in Worklist, choose **Check confirmed
intake for alerts**, then open **Alerts**. Confirm treatment purpose and refresh.
Acknowledge explicitly; acknowledgement records ownership but does not resolve
the concern. The owning doctor can record a separate resolution with rationale.
Resolved alerts remain available with **Include resolved alerts**.

Assisted and touch intake also evaluate each confirmed answer and save any triggered
flags before requesting the next AI question. The first complaint can immediately
pause questions and ask the patient to call nearby staff. A failed safety check
shows a manual assistance message and prevents the next AI request.

This is a prototype workflow, not clinically approved automatic triage.
Governed handoff/override and external
notification remain pending. Do not infer delivery from a stored alert. Existing alerts are
not deleted when prototype evaluation is disabled.

## Alert event delivery

Migration 0016 adds delivery fencing and dead-letter state. Start the optional
publisher with `docker compose --profile triage up -d --build triage-outbox-publisher`.
It uses `DATABASE_MAINTENANCE_URL` for the alert-owned outbox and publishes
metadata-only events to `TRIAGE_EVENT_TOPIC` (default `clinical.triage.v1`).

The queue distinguishes pending, failed and broker-published events. Broker
publication is not a notification-provider delivery receipt or staff acknowledgement.
After five failed/crashed attempts, an event stays available for operator review;
later events for that alert wait behind it. Correct the outage, inspect the exact
failed event ID, then use the maintenance-only command:

```powershell
python -m app.rules.alert_outbox replay --event-id <failed-event-uuid>
```

Replay preserves the event ID; consumers must deduplicate it. This command needs
the maintenance database environment and does not resolve or acknowledge an alert.
It is not a staff/public API. Record the replay in the facility's operations log.
To stop delivery while preserving alerts, stop the publisher container. Do not
run the down migration to handle an outage; retain queued events and history.

## Prototype alert escalation timers

For the synthetic demo tenant only, apply migration 0017 and enable
`TRIAGE_WORKFLOW_ENABLED=true` and `ENABLE_DEMO_ROUTES=true`. From `apps/api`,
set `DATABASE_MAINTENANCE_URL` to the local maintenance connection, then run:

```powershell
python -m app.rules.alert_timers status --policy ../../services/alert-worker/policy.example.json
python -m app.rules.alert_timers activate --policy ../../services/alert-worker/policy.example.json --operator-id <operator-uuid> --expected-revision 0 --reason-code initial_activation
```

Use the revision returned by `status`; zero applies only to the first activation.
From the repository root, start the worker:

```powershell
docker compose --profile triage-timers up -d --build triage-timer-worker
```

`TRIAGE_TIMER_POLICY_FILE` optionally selects a different policy JSON file. The
default example in `services/alert-worker/policy.example.json` uses 30- and
120-second showcase deadlines; these are not clinically approved response times.
Each due step moves an unacknowledged alert to doctor escalation and records an
outbox event. Acknowledged/resolved alerts do not expire on this timer. Repeated
scans and restarts retain completed steps. Kafka publication remains separate;
run the triage outbox publisher when demonstrating broker delivery.

Stop `triage-timer-worker` to pause scheduling. Restart catches up overdue steps.
Use the `deactivate` command with operator ID, current revision and reason to pause
scheduling centrally. Old policy workers cannot write after replacement or
deactivation commits. Version and review policy changes: replacements apply to
outstanding alerts using their original creation times. Operator identity and
clinical approval still require production governance.
No policy or timer can resolve an alert. See `services/alert-worker/README.md`.
