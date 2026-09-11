# ADR-009: Patient self-scope and deterministic mock TTS

## Status

Accepted — 2026-09-05.

## Context

The patient application needs to submit confirmed intake, manage treatment
consent, upload documents and read clinician-signed reports. Kiosk pre-auth is
deliberately PHI-free, while record access requires an authenticated patient
identity. The local demonstration also needs audible feedback without model
downloads, cloud speech APIs or API keys.

Two superficially convenient approaches are unsafe: accepting a patient ID in
each request would permit insecure direct-object references, and treating raw
OCR or unsigned summaries as patient records would bypass clinician review.
Browser speech synthesis would also make the provider and privacy boundary
depend on the browser/operating system.

## Decision

- The production patient surface is `apps/patient-kiosk`. The README-only
  `frontend/apps/patient-dashboard` directory is not a second runtime.
- Authenticated patient endpoints live under `/api/v1/patient-portal/me`.
  Tenant, patient and permitted facilities come from the verified token; the
  client never selects a patient record owner.
- Kiosk pre-auth can start an opaque intake session only. It cannot list reports,
  consents, documents or timeline data.
- Patients may create/revoke their own bounded treatment consent, submit a
  confirmed intake and upload a document only within that active consent.
- Patients can see clinician-signed summaries and clinician-reviewed document
  timeline entries. Draft summaries, raw OCR, rejected candidates and other
  patients' records are not returned.
- Local demo identity uses fixed synthetic UUIDs and the demo token endpoint.
  That route remains disabled unless `ENABLE_DEMO_ROUTES=true`; it is not the
  production authentication design.
- `TTS_PROVIDER=mock` is the only supported TTS provider. It creates a local,
  deterministic WAV acknowledgement cue. It is intentionally not intelligible
  clinical speech and makes no network call. Unsupported values fail closed.

## Consequences

- Patient routes are self-scoped and return not-found for inaccessible objects,
  limiting record enumeration.
- Clinical narrative responses use private/no-store headers and downloads are
  plain UTF-8 clinician-signed reports with an integrity hash.
- The complete local ASR-to-response loop can exercise capture, confirmation,
  adaptive SOCRATES dialogue, persistence and audible status without a hosted
  provider. Production-quality speech remains a separately governed capability.
- A future TTS provider requires a new decision covering language quality,
  accessibility, privacy, residency, retention, failure behavior and evaluation.

## Alternatives considered

### Patient ID supplied in request bodies

Rejected because authorization must derive record ownership from the verified
identity, not from mutable client input.

### Raw OCR in the patient timeline

Rejected because OCR is untrusted extraction. Only clinician-reviewed facts may
cross into the patient-visible clinical timeline.

### Browser or hosted speech synthesis

Rejected for the current scope because execution, retention and provider
behavior would be platform-dependent or external. The deterministic mock cue is
honest about what is implemented.
