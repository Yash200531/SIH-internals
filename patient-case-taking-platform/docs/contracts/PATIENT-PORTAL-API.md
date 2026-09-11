# Patient portal API contract

## Boundary

All record-bearing routes require a verified access token with `role=patient`,
an internal patient UUID in `sub`, a tenant UUID and at least one permitted
facility. Every route derives the patient from that identity. There is no
`patient_id` request parameter.

The local demo can mint a synthetic token only when `ENABLE_DEMO_ROUTES=true`.
That mechanism is for local engineering and must not be enabled in a shared or
clinical environment.

## Endpoints

| Method and path | Result | Safety rule |
|---|---|---|
| `GET /api/v1/patient-portal/me/dashboard` | Counts and recent signed/reviewed items | Self and permitted facilities only |
| `GET /api/v1/patient-portal/me/reports` | Clinician-signed summaries | Never returns drafts or rejected versions |
| `GET /api/v1/patient-portal/me/reports/{id}` | Full signed summary with evidence paths | Inaccessible IDs are returned as not found |
| `GET /api/v1/patient-portal/me/reports/{id}/download` | UTF-8 signed report | Private/no-store; includes signature SHA-256 |
| `GET /api/v1/patient-portal/me/timeline` | Clinician-reviewed document facts | Never returns raw OCR or unreviewed candidates |
| `POST /api/v1/patient-portal/me/consents` | Bounded treatment consent | Patient comes from token |
| `GET /api/v1/patient-portal/me/consents` | Patient's consent versions | Self only |
| `POST /api/v1/patient-portal/me/consents/{id}/revoke` | Revoked consent version | Cannot revoke another patient's consent |
| `POST /api/v1/patient-portal/me/intakes` | Durable confirmed intake decision | Active, matching consent and `Idempotency-Key` required |
| `GET /api/v1/patient-portal/me/documents` | Patient upload states | Self and permitted facilities only |
| `POST /api/v1/patient-portal/me/documents` | Registers an upload | Active treatment consent required |
| `POST /api/v1/patient-portal/me/documents/{id}/upload-session` | Exact-object upload grant | Short-lived quarantine target |
| `POST /api/v1/patient-portal/me/documents/{id}/finalize` | Verifies and queues upload | Size, MIME and checksum are server verified |
| `POST /api/v1/patient-portal/me/documents/{id}/cancel` | Cancels eligible upload | Optimistic version required |
| `POST /api/v1/tts/synthesize` | Deterministic WAV status cue | `mock` only; no external network |

## Intake truth boundary

### Authenticated intake sessions

`POST /api/v1/patient-portal/me/sessions` accepts `facility_id` and `language`
(`hi` or `en`) plus a UUID `Idempotency-Key` header. Patient and tenant come from
the authenticated internal identity. The response contains server-generated
`id`, `encounter_id`, permitted `facility_id`, `language`, `expires_at` and
`hard_expires_at`. Replaying the same active request returns the same identifiers;
changing its input or replaying an expired/ended session returns 409. A facility
outside the patient's grant returns 403.

`POST /sessions/{id}/touch` renews an active session's five-minute idle expiry,
bounded by its thirty-minute hard expiry. `POST /sessions/{id}/end` ends it.
Both paths are relative to `/api/v1/patient-portal/me`. Wrong patient, tenant,
facility or login-session ownership and inactive IDs produce the same 404.
Expiry cannot be renewed after it occurs. Responses are private/no-store.

Migration 0019 stores session ownership as a hash of verified provider/session
identity, with tenant/patient RLS and immutable creation/end history. Clerk token
refresh retains ownership; a different login or application does not. Demo
credentials without a stable session ID are bound to that exact token. Consent
and clinical content are not stored in this table. The down migration removes
session/history metadata and requires an appropriate backup before use outside
disposable tests.

The patient start flow uses this endpoint. ASR requires its server-issued
`session_id`: a query field on `/ws/asr` and a required multipart form field on
`POST /api/v1/asr/transcribe`. Both paths verify active session ownership and
matching encounter before inference and before returning transcripts. Expired,
ended, wrong-login or mismatched sessions receive 403 (WebSocket access-denied
error and close 1008). Processing does not renew session activity automatically.
Intake actions and automatic activity/end handling remain pending integration.

Staff handoff uses `GET /api/v1/intake-worklist?purpose=treatment` with a doctor
or nurse token. Results are paged with `limit` (1–100) and `offset` (0–10000),
restricted to the token's tenant/facilities, accepted intake decisions and active
matching treatment consent. Rejected or revoked-consent intakes are excluded.
Responses are private/no-store and preserve patient-confirmed answers.

`POST /api/v1/intake-worklist/{id}/confirm` requires `reviewed: true` and an
optional `expected_version`. It rechecks visibility and loads the intake from
PostgreSQL, then records the clinician-confirmed Phase 8 context. Stale versions
return 409; inaccessible/revoked entries return 404. It does not copy the
patient's proposed summary into a signed record or sign anything automatically.
The existing `/summary-workflows/generate` endpoint then assembles the confirmed
context and reviewed document facts. The worklist uses a stable intake-based
idempotency key and reopens an existing generation after an interrupted response.
Read/confirmation audits use the existing metadata-only audit emitter; durable
central audit persistence remains a separate unresolved platform gap.

An accepted or rejected summary draft is stored as the patient's confirmed
submission, not as a signed clinical record. A clinician must assemble the
confirmed context, review evidence, edit as needed and sign through the Phase 8
workflow before it appears in patient reports.

The S2S path is:

`audio capture → ASR result → patient confirmation/edit → mock adaptive dialogue → mock WAV status cue → accepted/rejected intake persistence`

Emergency-rule output interrupts routine questions. The mock dialogue and mock
TTS providers do not diagnose, prescribe, or imply that an emergency service has
been contacted.

## Caching and logging

Patient clinical responses are marked private/no-store. Audit and operational
events contain opaque IDs, action, role, status and error class only; complaint
text, answers, OCR text and report narrative must not enter metadata logs.
