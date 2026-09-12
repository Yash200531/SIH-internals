# Frontend Build Plan

## Stage 1 — Foundation

- Establish the Next.js/React TypeScript monorepo, package manager and task runner.
- Establish TypeScript, formatting, linting, test and accessibility gates.
- Integrate separate Clerk applications/audiences for patient, doctor and administration surfaces.
- Build the typed FastAPI client, session adapters and internal authorization primitives.
- Define design tokens, multilingual typography, icons and accessible components.
- Implement PHI-safe frontend telemetry.

Exit: each application deploys independently, authenticates through Clerk, rejects cross-application audiences and passes backend authorization tests.

## Stage 2 — Patient workflow slice

- Language/accessibility onboarding.
- Patient registration and identity confirmation.
- Opaque kiosk pre-auth intake that cannot search or display PHI.
- Voice/text case-taking with repeat, correction and explicit confirmation.
- Offline/sync status and shared-device reset.
- Patient-friendly approved summary.

Exit: a synthetic patient completes an assisted Hindi/English flow without doctor/admin bundle access.

## Stage 3 — Doctor workflow slice

- Facility worklist and safe patient selection.
- Source-linked case review and unresolved questions.
- Timeline, allergies, medications and red flags.
- Draft editing, validation and clinician sign-off.
- Manual workflow when AI services are unavailable.

Exit: doctor completes and signs a synthetic encounter with visible provenance and audit evidence.

## Stage 4 — User administration

- Workforce account lifecycle.
- Facility membership and role assignment.
- Session/device revocation.
- Access review and audit views.
- Step-up authentication for high-risk changes.

Exit: least-privilege user administration works without granting clinical access.

## Stage 5 — Integration and hardening

- ABDM consent/identity states in relevant patient and operator views.
- Cross-application contract tests.
- Accessibility and multilingual field testing.
- CSP, session, upload preview and dependency security testing.
- Performance budgets and low-bandwidth validation.

## Frontend acceptance gates

- Zero cross-role route exposure in automated tests.
- Backend denies every unauthorized request even if UI checks are bypassed.
- Keyboard and screen-reader navigation pass for all critical workflows.
- Patient workflow passes comprehension testing with intended users.
- Clinical data is absent from analytics, browser error payloads and generic persistent storage.
