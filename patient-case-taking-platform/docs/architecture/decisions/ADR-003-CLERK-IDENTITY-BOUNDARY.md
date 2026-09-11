# ADR-003: Use Clerk Behind an Internal Identity Boundary

## Status

Accepted for planning.

## Decision

Use Clerk to authenticate staff and patient web sessions. Use hospital SSO where available through supported OIDC/SAML integration. FastAPI validates Clerk-issued tokens and maps the external subject to an internal workforce, patient or caregiver identity before applying internal authorization.

Clerk does not own facility membership, care relationships, consent, purpose-of-use, break-glass policy or clinical-record access. Those decisions remain in the platform authorization layer.

Kiosk pre-auth may create an opaque, expiring intake session with no record-search or PHI-read capability. Access expands only after verified patient authentication or an attributed staff-assisted workflow.

## Consequences

- Separate Clerk application/audience configuration is required for patient, doctor and user-administration surfaces.
- Token verification tests cover issuer, audience, authorized party/client, signature, expiry and key rotation.
- Clerk webhooks are signature-verified, idempotent lifecycle inputs; they do not directly grant clinical authorization.
- Internal identities and clinical records survive an identity-provider migration.
- Hospital SSO account-linking, duplicate identities, revocation lag and provider outage require explicit runbooks.

## Exit criteria

- Cross-application tokens are rejected by both frontend middleware and FastAPI.
- Kiosk pre-auth cannot retrieve PHI in automated security tests.
- Account linking/unlinking and provider outage behavior are approved by security and clinical operations.
