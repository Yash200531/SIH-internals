# Frontend Workspace

Frontend monorepo boundary for three separately deployable experiences:

- `apps/user-admin-dashboard`: workforce users, roles, facilities and audit administration;
- `apps/doctor-dashboard`: worklist, patient context, clinical review and signed notes;
- `apps/patient-dashboard`: identity, consent, voice case-taking, records and caregiver workflows.

The applications share stable packages, not feature implementations. Each application has independent routes, authorization policies, build output, tests and deployment configuration.

## Selected stack

Use a Next.js/React TypeScript monorepo with PWA support. Patient, doctor and user-administration experiences remain separate deployable applications within one codebase. Clerk supplies authentication components/session issuance; backend authorization remains authoritative.

## Directory tree

```text
frontend/
├── README.md
├── AGENTS.md
├── CONTEXT-GRAPH.md
├── apps/
│   ├── user-admin-dashboard/
│   │   ├── src/{app,features,components,lib,styles}
│   │   └── tests/
│   ├── doctor-dashboard/
│   │   ├── src/{app,features,components,lib,styles}
│   │   └── tests/
│   └── patient-dashboard/
│       ├── src/{app,features,components,lib,styles}
│       └── tests/
├── packages/
│   ├── api-client/
│   ├── auth-session/
│   ├── authorization/
│   ├── design-system/
│   ├── accessibility/
│   ├── i18n/
│   ├── clinical-types/
│   ├── telemetry/
│   ├── config/
│   └── test-utils/
├── tests/e2e/{user-admin,doctor,patient,cross-role}/
├── tooling/{eslint,typescript,build}/
└── docs/
    ├── FRONTEND-ARCHITECTURE.md
    ├── ROUTE-ACCESS-MATRIX.md
    └── BUILD-PLAN.md
```

## Boundary rules

1. A patient session cannot load doctor or administration bundles/routes.
2. A doctor cannot gain administrative capability through hidden UI controls.
3. UI authorization improves safety but backend authorization remains authoritative.
4. Apps import shared packages through public exports only.
5. Shared packages contain primitives and contracts, not app-specific workflows.
6. PHI is never persisted in generic browser storage, analytics or error reports.
7. Patient accessibility and multilingual behavior are release requirements.
8. Each application has a separate Clerk audience/client configuration and cannot accept another application's session audience.
9. Kiosk pre-auth can create only a short-lived intake session and cannot search or render PHI.

## Start here

1. [`CONTEXT-GRAPH.md`](CONTEXT-GRAPH.md)
2. [`docs/FRONTEND-ARCHITECTURE.md`](docs/FRONTEND-ARCHITECTURE.md)
3. [`docs/ROUTE-ACCESS-MATRIX.md`](docs/ROUTE-ACCESS-MATRIX.md)
4. [`docs/BUILD-PLAN.md`](docs/BUILD-PLAN.md)
