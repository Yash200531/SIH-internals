# Frontend Architecture

## Deployment boundary

Maintain three separate Next.js applications in one TypeScript monorepo rather than a single role-switched dashboard. This provides clearer ownership, smaller permission surfaces, independent release cadence and simpler role-specific UX while preserving shared UI/API packages.

All three applications use Clerk, but each receives its own audience/client configuration and allowed callback URLs. Hospital SSO is connected through the identity boundary where available. The kiosk may start an opaque pre-auth intake flow, but it cannot retrieve PHI before verified patient or attributed staff authorization.

## Application layers

| Layer | Responsibility |
|---|---|
| `src/app` | route composition, layouts, providers and error boundaries |
| `src/features` | user-visible business capabilities and feature state |
| `src/components` | app-specific composite presentation components |
| `src/lib` | app-owned adapters and utilities without business UI |
| `src/styles` | app theme entry point and global styling |
| `tests` | application integration and route tests |

## State rules

- Server data is fetched through the typed API client and remains the backend's authority.
- URL state represents shareable navigation/filter state where privacy permits.
- Short-lived form/session state stays in memory.
- Offline patient drafts use an encrypted, explicit queue with expiry and user-visible deletion.
- Do not copy server data into a general global store without a measured need.

## Authentication and authorization

- Use Clerk's Next.js integration with secure, HTTP-only session handling where supported; never persist bearer tokens in `localStorage`.
- Send Clerk tokens only to the intended FastAPI audience. FastAPI validates tokens and applies internal authorization.
- Route middleware provides early redirects, not final authorization.
- Every backend request is authorized independently.
- Step-up authentication is required for sensitive administration, exports and break-glass access.
- Session expiry must preserve safe unsaved work without leaking data to another shared-device user.
- Clerk outage handling may preserve an already verified, bounded clinical session according to policy, but must not create new privileged sessions or silently bypass verification.

## Error and loading behavior

- Each route group has loading, empty, error and permission-denied states.
- Doctor signing clearly distinguishes saved draft, pending sync and signed state.
- AI/provider failure degrades to manual entry.
- Patient offline behavior never implies that unsynchronized clinical data reached the hospital.

## Security

- Apply strict CSP, frame protection, secure cookies and dependency integrity controls.
- Sanitize uploaded/rich document previews and never trust OCR/LLM markup.
- Redact clinical request/response bodies from monitoring.
- Clear sensitive memory/session state on logout, role change and kiosk reset.
