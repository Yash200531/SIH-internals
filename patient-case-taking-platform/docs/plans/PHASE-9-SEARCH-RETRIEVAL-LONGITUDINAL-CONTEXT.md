# Phase 9: Search, Retrieval and Longitudinal Context

## Status

**Implementation in progress. Not complete.**

This plan replaces the unsupported completion report supplied on 5 September
2026. Completion must be earned section by section using repository, API,
container and browser evidence recorded below.

## Claim audit

| Supplied claim | Repository evidence on 2026-09-05 | Disposition |
|---|---|---|
| `apps/api/src/services/search_service.py` exists | Path is absent; the API uses `apps/api/app` | Build in the real package layout |
| FHIR R4 search is implemented | Existing FHIR code renders demo resources; it does not parse or execute FHIR search | Implement only resource searches backed by canonical data |
| Elasticsearch indexes patient records | No Elasticsearch service, client or index exists | Add a real rebuildable projection and local service |
| Longitudinal multi-encounter timeline exists | Phase 7 exposes reviewed-document facts only | Aggregate signed summaries and reviewed facts |
| Access and audit are complete | Existing general audit emitter is in-memory; no search authorization/audit exists | Add fail-closed authorization and durable query metadata |
| Performance and relevance targets passed | No harness, corpus or result artifact exists | Add reproducible engineering benchmarks; publish measured values only |
| Cross-provider linking is complete | No ABDM/external record-linking implementation exists | Limit to authorized facilities sharing one internal patient ID |

## Objective

Give patients and care staff fast, explainable retrieval over MediKiosk records
that have already crossed a human-review boundary. PostgreSQL remains clinical
truth. Elasticsearch is a disposable, rebuildable read model. Search must not
turn raw OCR text, mock clinical-generation output or unsigned drafts into
clinical facts. Document OCR itself uses the real PP-OCRv5 mobile worker; its
output becomes searchable only after clinician review and fact promotion.

## Users and allowed operations

| Role | Search scope | Timeline | Export |
|---|---|---|---|
| Patient | Own internal patient ID and token-permitted facilities | Own timeline | Own results as CSV |
| Doctor | Explicit patient ID inside token-permitted facilities | Permitted patient | CSV |
| Nurse | Explicit patient ID inside token-permitted facilities | Permitted patient | Not allowed |
| Admin or unsupported role | Denied | Denied | Denied |

Every operation requires a declared treatment purpose. Tenant, role and
facility scope come only from the validated token. The API never accepts a
tenant ID from the client.

## Canonical source boundary

Phase 9 may index:

- `clinical_summary_workflow` rows with status `signed`;
- active `reviewed_document_fact` rows whose source document belongs to an
  authorized facility;
- source identifiers, encounter identifiers, event dates and statement status
  needed to explain the hit.

Phase 9 must never index:

- raw OCR text, page images or transcript content;
- draft, in-review, rejected or superseded summaries;
- unreviewed extraction candidates;
- patient data from another tenant/facility;
- invented diagnoses, lab values, procedures or current-medication assertions.

## Search projection contract

One Elasticsearch document represents one canonical source record.

```python
class ClinicalSearchRecord(BaseModel):
    record_id: str
    tenant_id: UUID
    facility_id: UUID
    patient_id: UUID
    encounter_id: UUID
    source_kind: Literal["signed_summary", "reviewed_fact"]
    source_id: UUID
    title: str
    content: str
    entity_type: str | None
    statement_status: str | None
    occurred_at: datetime
    security_labels: list[str]
```

The public response omits `tenant_id` and returns bounded highlights plus source
references. Elasticsearch queries always include exact tenant, patient and
facility filters before scoring.

## Supported retrieval

### Clinical search API

`GET /api/v1/clinical-search`

Supported parameters:

- `patient_id` for doctor/nurse; ignored and derived from identity for patient;
- `q` with a maximum of 200 characters;
- `source_kind`, `entity_type`, `from`, `to` and repeated `facility_id` filters;
- `page_size` from 1 to 50 and opaque `cursor` pagination;
- required `purpose=treatment`.

Response fields include total, hits, safe highlights, source-kind facets,
entity-type facets, took time and next cursor. Query-string syntax, arbitrary
field selection and scripts are not exposed.

### Longitudinal timeline API

`GET /api/v1/clinical-search/timeline/{patient_id}` for staff and
`GET /api/v1/patient-portal/me/longitudinal-timeline` for patients.

The timeline merges signed-summary events and reviewed facts, sorts them
deterministically, supports date/source filters and reports truthful summary
counts. It does not infer medication activity, diagnosis state or lab trends.

### FHIR R4 search API

The Phase 9 search-set boundary supports only:

- `GET /api/v1/fhir-search/DocumentReference?patient={id}&date={prefix}{date}`
  for signed summaries;
- `GET /api/v1/fhir-search/Basic?patient={id}&created={prefix}{date}&code={entity}`
  for reviewed facts.

It returns a FHIR R4 `Bundle` with `type=searchset`, self/next links and total.
Unsupported resource types or parameters return a bounded `OperationOutcome`.
Patient, Encounter, Condition, MedicationRequest and Observation search are
future slices that require durable canonical resources and mappings first.

## Index design

- Local/reproducible baseline: Elasticsearch server and async Python client
  `9.3.0`.
- Alias: `medikiosk-clinical-search`; versioned backing index for atomic rebuild.
- Exact keyword fields: all IDs, source kind, entity type, statement status and
  security labels.
- Text fields: title/content using a Unicode-safe standard analyzer, lowercase,
  ASCII folding with original tokens retained, and a small reviewed synonym
  graph stored with the API at `app/search/medical_synonyms.json` so the same
  reviewed artifact is packaged into the search container.
- Dates use strict Elasticsearch date mapping.
- Highlight fragments are bounded and source text is never returned wholesale
  from the index.
- Index data is derived and may be deleted/rebuilt without losing clinical truth.

## Synchronization and recovery

1. Summary and document transactional outboxes remain the durable event source.
2. A search consumer reads `clinical.summaries.v1` and
   `clinical.documents.v1` with its own Kafka consumer group.
3. Only signed-summary, fact-promotion and fact-withdrawal events trigger work.
4. The consumer reloads canonical rows under tenant context, then upserts or
   deletes the corresponding search records.
5. Elasticsearch outages do not roll back clinical writes. Kafka offsets are
   committed only after successful indexing; retries are bounded and observable.
6. A tenant-scoped repair deletes/reloads only that tenant's derived records,
   then compares canonical and indexed opaque IDs/counts. A versioned backing
   index is atomically swapped only when the complete canonical corpus is loaded;
   an incomplete tenant list must never replace a shared alias.

## Durable search audit

Migration `0014` adds `clinical_search_audit` with forced tenant RLS. Each
search, timeline read, FHIR search and export records actor, role, purpose,
authorized facilities, query hash, filter metadata, result count, latency and
outcome. Raw query text and returned clinical content are not persisted in the
audit row.

## API and failure behavior

- Missing/invalid auth: 401.
- Unsupported role, patient scope or facility: 403 without revealing existence.
- Invalid parameter/FHIR search: 400/422 with no backend query leakage.
- Elasticsearch unavailable: 503 and a retry-safe response; direct patient
  signed reports and Phase 7 timeline remain available.
- Export is streamed CSV with private/no-store headers and spreadsheet-formula
  neutralization.
- Every response carries a correlation identifier.

## User interface

### Clinician console

- Add a real `/search` page and sidebar entry.
- Require a patient ID and purpose before querying.
- Provide text search, source/date/entity filters, facets, empty/error/loading
  states, safe highlights and a chronological toggle.
- Doctor-only CSV export; nurse UI hides and the API denies export.

### Patient portal

- Extend `/records` with a longitudinal view backed by the self-scoped endpoint.
- Keep the existing signed-report and reviewed-fact cards available when search
  infrastructure is unavailable.

## Commands

```powershell
# API quality
cd apps/api
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m pytest -q

# Frontend quality
cd apps/clinician-console
npm run lint
npm run build

# Local Phase 9 services and integration
docker compose up -d postgres kafka elasticsearch
docker compose run --rm api-migrate
$env:PHASE9_INTEGRATION='1'
.\.venv\Scripts\python.exe -m pytest tests\test_phase9_search_integration.py -q

# Reconcile/repair one tenant, then run a disposable synthetic benchmark
docker compose run --rm search-index-worker python -m app.search.worker reconcile-tenant --tenant-id <uuid>
docker compose run --rm search-index-worker python -m app.search.worker rebuild-tenant --tenant-id <uuid>
docker compose run --rm search-index-worker python -m tools.verify_phase9_search --record-count 250 --iterations 5
```

## Testing strategy

- Unit: contracts, authorization, query builder, cursor validation, FHIR date
  prefixes, Bundle mapping, timeline merge, CSV neutralization and synonym config.
- HTTP: role/patient/facility isolation, invalid input, unavailable-search 503,
  response privacy and audit calls.
- PostgreSQL: migration/up/down, forced RLS and durable metadata-only audit.
- Elasticsearch: real index creation, bulk upsert/delete, filters, facets,
  highlighting, synonyms and alias rebuild.
- Kafka: relevant-event routing, offset-after-success behavior and idempotent
  re-delivery.
- Browser: doctor and nurse workflows plus patient longitudinal fallback.
- Performance: frozen synthetic corpus and exact machine/corpus/result metadata;
  no extrapolation to one million records.

The measured local benchmark output is stored in
[`docs/evidence/phase9-search-benchmark.json`](../evidence/phase9-search-benchmark.json).
It contains 250 visible records plus one cross-tenant control, four golden
English/Hindi queries repeated five times, the exact runtime versions and
observed latency. All golden queries and ID reconciliation passed. This small
synthetic run is not representative clinical relevance or production capacity
evidence and defines no release SLO.

## Implementation tasks

### P9.0 — Correct the specification

- [x] Audit every supplied completion claim against repository state.
- [x] Replace invented metrics and unsupported resource claims with testable gates.
- [x] Add ADR-010 for the rebuildable clinical-search boundary.

### P9.1 — Search contracts and safe query construction

- [x] Add typed records, requests, hits, facets and opaque cursor contracts.
- [x] Add Unicode/medical synonym configuration and deterministic query builder.
- [x] Unit-test validation, scope filters, pagination and highlighting limits.

### P9.2 — Canonical projection and longitudinal assembly

- [x] Load signed summaries and active reviewed facts under tenant/facility scope.
- [x] Assemble deterministic multi-encounter timeline and truthful counts.
- [x] Prove raw OCR and unsigned summaries cannot enter either result.

### P9.3 — Real Elasticsearch adapter

- [x] Add Elasticsearch 9.3.0 client/service, health check and index mapping.
- [x] Implement index/search/facet/delete and versioned alias rebuild.
- [x] Pass real-container integration tests including synonym and isolation cases.

### P9.4 — Event-driven synchronization

- [x] Consume existing summary/document Kafka topics with a dedicated group.
- [x] Index only relevant events by re-reading canonical PostgreSQL state.
- [x] Prove retry, idempotent replay, deletion and offset-after-success behavior.

Evidence recorded 6 September 2026: the focused search/synchronization suite
passes; real Kafka-to-Elasticsearch replay and the real Elasticsearch isolation,
synonym, deletion and alias-rebuild cases pass; the packaged Compose worker is
running; and an empty synthetic tenant rebuild completed without touching
clinical records. The same run corrected the single-node Kafka internal-topic
replication settings and made migration checksums stable across LF/CRLF checkouts.

### P9.5 — Authorized APIs and durable audit

- [x] Add migration 0014 and tenant-scoped audit repository.
- [x] Add clinical search, timeline, patient-self timeline and doctor/patient CSV;
  deny nurse export.
- [x] Add supported FHIR search-set endpoints and bounded OperationOutcome errors.

Evidence recorded 6 September 2026: migration 0014 was applied by the packaged
Compose migration image; an unprivileged real-PostgreSQL test proved durable
metadata-only insertion, forced tenant RLS and cross-tenant read/write denial;
60 focused authorization/API/audit/search tests passed; the combined real
PostgreSQL, Elasticsearch and Kafka checkpoint passed; and the complete backend
gate passed with Ruff, mypy and 376 tests (25 explicitly gated integrations
skipped). The packaged API returned healthy liveness/readiness responses and a
correlated 401 from the new search route without authentication.

### P9.6 — Clinician and patient interfaces

- [x] Add accessible clinician search/timeline UI with complete states.
- [x] Add patient longitudinal view with direct-record fallback.
- [x] Browser-test doctor, nurse denial/export behavior and patient self-scope.

Evidence recorded 6 September 2026: both frontend lint gates and both clean
Next.js production builds passed; the packaged clinician and patient images
started and served their new routes; and browser testing with synthetic local
identities proved the doctor search/timeline and export control, nurse search
with doctor-only export messaging, and the Hindi patient self-scoped
longitudinal empty state with no browser-console errors. The browser run also
found and repaired an incorrect PostgreSQL bind count in the canonical timeline
reader; the focused projection/service regression suite now passes 14 tests,
and the repaired packaged API returns the timeline successfully. Raw OCR and
unsigned drafts are explicitly excluded from every displayed search state.

### P9.7 — Operations, benchmark and documentation

- [x] Add Compose worker/service, environment examples and setup runbook.
- [x] Add rebuild/reconciliation and reproducible synthetic benchmark tools.
- [x] Update architecture, safety, security, roadmap, todo, completed-work record
  and Phase 9 HTML ledger using measured evidence only.

Evidence recorded 6 September 2026: both environment examples declare the
document-event topic; the packaged search worker reconciled an empty canonical
tenant without creating a missing index, and its tenant rebuild returned exact
canonical/indexed agreement. The disposable 250-record benchmark passed all
four English/Hindi golden queries, excluded its cross-tenant control and
reconciled 250 canonical IDs to 250 indexed IDs; the exact output is stored in
[`docs/evidence/phase9-search-benchmark.json`](../evidence/phase9-search-benchmark.json).
The final backend gate passed Ruff, mypy across 160 source files, and 376 tests
with 25 explicitly gated provider/integration tests; the three real Phase 9
PostgreSQL/Elasticsearch/Kafka checks also passed. The setup guide, operations
runbook, architecture, safety, security, roadmap, status files and HTML ledger
now state the implemented boundary and retain the production rollout gates.

## Checkpoints

After P9.1–P9.2: unit tests, Ruff and mypy pass; canonical boundary is proven.

After P9.3–P9.5: real Postgres/Elasticsearch/Kafka integration passes; failure
behavior, access control and audit persistence are proven.

After P9.6–P9.7: frontend lint/build and browser workflows pass; the benchmark
and rebuild run produce stored evidence.

## Completion gate

Phase 9 may be labelled an **engineering candidate** only when every task above
is checked with current command output and linked evidence. It may not be called
production complete until identity, clinical/privacy approval, representative
relevance evaluation, load/security testing, backup/restore and rollback drills
also pass.
