# Internal identity and session API

HTTP bearer authentication and the ASR first-frame credential use the same
verification boundary. `AUTH_PROVIDER=demo` accepts local synthetic credentials
only in development/test. Issuing those credentials additionally requires demo
routes. `AUTH_PROVIDER=clerk` never falls back to demo credentials.

## Configuration

Apply migration 0018 before selecting Clerk. Set `CLERK_APPLICATIONS_JSON` to a
JSON array with one entry per application. Example with public placeholders:

```json
[{"issuer":"https://your-instance.clerk.accounts.dev","audience":"patient-app","authorized_parties":["https://patient.example.test"],"allowed_roles":["patient"]}]
```

Configure the matching audience in the issued session token. Staff applications
need separate audience/origin boundaries and an appropriate allowed-role list.
Issuer must be HTTPS without a trailing slash. No secret key is required for
public-key verification. The signed token must contain issuer, audience, subject,
session ID, authorized origin and time claims. External role, tenant and facility
claims never grant platform access.

## Provisioning

A verified external subject must have an active internal grant for its exact
issuer/audience. Provision with a maintenance database connection after verifying
the person's internal patient/staff identity and facility assignment:

```powershell
python -m tools.manage_identity --binding binding.json --operator-id OPERATOR_UUID --expected-version 0 --reason-code initial_provision
```

`DATABASE_MAINTENANCE_URL` is required. The bounded binding JSON contains `issuer`,
`audience`, `subject`, `internal_id`, `tenant_id`, `role`, `facility_ids` and `active`.
Use existing internal UUIDs. Version zero creates a grant; subsequent changes
require its current version. Changes append protected audit history atomically.
Internal identity/tenant relinking is rejected. A supplied operator UUID records
attribution; the CLI itself does not verify workforce authority. Keep this tool
within the controlled maintenance workflow. Never provision from browser claims.

## Endpoints

- `GET /api/v1/auth/me`: internal user/tenant UUID, role, facility IDs, token expiry
  and provider. Does not return the external credential or email.
- `POST /api/v1/auth/session/revoke`: revokes the caller's platform session. Clerk
  refreshes with the same session ID remain rejected across process restarts.
  This does not sign out of Clerk or revoke other platform/application sessions;
  the frontend must also invoke provider sign-out.

Both require bearer authentication and return `Cache-Control: private, no-store`.
Invalid credentials return 401; missing/inactive grants return 403; unconfigured
or unavailable verification returns 503. Grants and revocations are checked in
PostgreSQL for each authentication, including voice authorization rechecks.

## Migration and validation

0018 adds identity bindings, append-only grant history and revoked session IDs.
All use forced row-level security scoped to the verified issuer/audience/subject.
The down migration removes these tables and revocation history: only use it on
disposable data, or after a reviewed backup/rollback procedure. Switching to demo
is not a production rollback strategy.

`IDENTITY_INTEGRATION=1` enables real PostgreSQL/RLS and locally signed RSA session
tests. JWKS transport is synthetic in these tests. Real configured Clerk issuance,
frontend sign-in and workforce provisioning still require deployment validation.

## Clinician web configuration

The clinician console supports Clerk with `@clerk/nextjs` 7.9.1. For direct Next.js
development, use its `.env.example`: set `NEXT_PUBLIC_AUTH_PROVIDER=clerk`, the
publishable key, server-only secret key, `CLERK_AUDIENCE` and comma-separated
`CLERK_AUTHORIZED_PARTIES`. Configure these to match the API's clinician boundary
and grant only the internal doctor/nurse roles appropriate to this application.
The issued session token must contain the exact configured audience.

Compose uses the `CLINICIAN_*` variables in the root example. Rebuild the clinician
image after changing public settings; Next.js embeds these during its build. The
secret key is supplied at runtime only. `/login` renders Clerk's sign-in UI in
Clerk mode. Other routes require Clerk authentication through Next.js proxy;
missing configuration returns 503 instead of enabling demo authentication.

Before mounting record screens, the client verifies `/auth/me` for an internal
clinical role and facility. Each API request obtains the current SDK session
token; Clerk tokens are never copied into sessionStorage. Sign-out first revokes
the platform session and then invokes Clerk sign-out. Revocation failures remain
visible with a retry action. Existing local demo access remains available in
explicit demo mode. The API remains authoritative for every record access.

SDK sources: https://clerk.com/docs/nextjs/getting-started/quickstart and
https://clerk.com/docs/nextjs/reference/hooks/use-auth . Local SDK inspection
confirmed optional audience handling; the proxy adds a mandatory exact audience
check to reject missing or cross-application audiences.
