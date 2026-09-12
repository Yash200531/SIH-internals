# Frontend Working Context

## Required reading order

1. `frontend/README.md`
2. `frontend/CONTEXT-GRAPH.md`
3. the target application's `README.md`
4. route/access matrix
5. relevant shared-package README
6. affected tests

## Non-negotiable rules

- Do not share route trees or feature state between patient, doctor and admin applications.
- Do not rely on hidden/disabled controls as authorization.
- Do not store access tokens or clinical payloads in `localStorage`.
- Do not send names, ABHA identifiers, transcripts or medical content to analytics.
- Do not render model output as clinician-approved content without a visible status.
- Do not create a second copy of shared clinical/API types inside an app.
- Patient-facing critical actions require simple-language confirmation and recovery paths.
- Clerk authenticates the session; FastAPI authorization remains authoritative.
- Patient, doctor and administration apps must reject tokens issued for another app audience.
- Kiosk pre-auth must never unlock record search or PHI display.

## Feature module shape

When implemented, each feature should prefer:

```text
feature-name/
├── api/
├── components/
├── hooks/
├── model/
├── routes/
├── tests/
└── index.ts
```

Only `index.ts` is public outside the feature.
