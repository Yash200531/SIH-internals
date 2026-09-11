# ABDM Integration Plan

## Boundary

The ABDM adapter owns gateway authentication, callbacks, request correlation, schema mapping, retry/reconciliation and sandbox/production configuration.

The clinical platform owns internal patient identity, local consent policy, encounters and signed records.

## Principles

- ABHA is optional for receiving care.
- Store ABHA as an external identifier, not a primary key.
- Separate ABHA verification from application login and workforce authorization.
- Implement explicit patient linking and unlinking states.
- Reconcile asynchronous callbacks; do not assume immediate success.
- Preserve consent request, grant, denial, expiry and revocation evidence.
- Map internal clinical records to validated FHIR R4/ABDM profiles at the integration boundary.

## Milestones

1. Register sandbox application and callback endpoint.
2. Implement credential rotation and gateway session handling.
3. Implement patient discovery/linking in test environment.
4. Implement consent request and notification lifecycle.
5. Implement HIP data-share flow if the platform publishes records.
6. Implement HIU data-request flow if the platform consumes records.
7. Validate FHIR bundles, encryption and callback retries.
8. Complete production readiness and facility onboarding requirements.

